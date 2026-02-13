from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType, TaskType
import json


class BuildingRedisManager:
    """건물 전용 Redis 관리자 - Task Manager와 Cache Manager 컴포넌트 조합 (비동기 버전)"""
    
    def __init__(self, redis_client):
        # 두 개의 매니저 컴포넌트 초기화
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.BUILDING)
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.BUILDING)
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간
    
    def validate_task_data(self, building_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """건물 데이터 유효성 검증"""
        return isinstance(building_idx, int) and building_idx > 0
    
    # === Task Manager 위임 메서드들 ===
    async def add_building_to_queue(self, user_no: int, building_idx: int, completion_time: datetime) -> bool:
        """건물을 완료 큐에 추가"""
        if not self.validate_task_data(building_idx):
            return False
        return await self.task_manager.add_to_queue(user_no, building_idx, completion_time)
    
    async def remove_building_from_queue(self, user_no: int, building_idx: int) -> bool:
        """건물을 완료 큐에서 제거"""
        return await self.task_manager.remove_from_queue(user_no, building_idx)
    
    async def get_building_completion_time(self, user_no: int, building_idx: int) -> Optional[datetime]:
        """건물 완료 시간 조회"""
        return await self.task_manager.get_completion_time(user_no, building_idx)
    
    async def update_building_completion_time(self, user_no: int, building_idx: int, new_completion_time: datetime) -> bool:
        """건물 완료 시간 업데이트"""
        return await self.task_manager.update_completion_time(user_no, building_idx, new_completion_time)
    
    async def get_completed_buildings(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 건물들 조회"""
        return await self.task_manager.get_completed_tasks(current_time)
    
    async def speedup_building(self, user_no: int, building_idx: int) -> bool:
        """건물 즉시 완료"""
        return await self.task_manager.update_completion_time(user_no, building_idx, datetime.utcnow())
    
    # === Hash 기반 캐싱 관리 메서드들 ===
    
    async def cache_user_buildings_data(self, user_no: int, buildings_data: Dict[str, Any]) -> bool:
        """Hash 구조로 건물 데이터 캐싱"""
        if not buildings_data:
            return True
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'building_count': len(buildings_data),
                'user_no': user_no
            }
            
            # Cache Manager를 통해 Hash 형태로 저장
            success = await self.cache_manager.set_hash_data(
                hash_key, 
                buildings_data, 
                expire_time=self.cache_expire_time
            )
            
            if success:
                # 메타데이터도 저장
                await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
                print(f"Successfully cached {len(buildings_data)} buildings for user {user_no} using Hash")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error caching buildings data: {e}")
            return False
    
    async def get_cached_building(self, user_no: int, building_idx: int) -> Optional[Dict[str, Any]]:
        """특정 건물 하나만 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            building_data = await self.cache_manager.get_hash_field(hash_key, str(building_idx))
            
            if building_data:
                print(f"Cache hit: Retrieved building {building_idx} for user {user_no}")
                return building_data
            
            print(f"Cache miss: Building {building_idx} not found for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached building {building_idx} for user {user_no}: {e}")
            return None
    
    async def get_cached_buildings(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 건물을 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            buildings = await self.cache_manager.get_hash_data(hash_key)
            
            if buildings:
                print(f"Cache hit: Retrieved {len(buildings)} buildings for user {user_no}")
                return buildings
            
            print(f"Cache miss: No cached buildings for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached buildings for user {user_no}: {e}")
            return None
    
    async def update_cached_building(self, user_no: int, building_idx: int, building_data: Dict[str, Any]) -> bool:
        """특정 건물 캐시 업데이트"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # Cache Manager를 통해 Hash 필드 업데이트
            success = await self.cache_manager.set_hash_field(
                hash_key, 
                str(building_idx), 
                building_data,
                expire_time=self.cache_expire_time
            )
            
            
            if success:
                await self.redis_client.sadd("sync_pending:building", str(user_no))
                
                print(f"Updated cached building {building_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error updating cached building {building_idx} for user {user_no}: {e}")
            return False
    
    async def remove_cached_building(self, user_no: int, building_idx: int) -> bool:
        """특정 건물을 캐시에서 제거"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            success = await self.cache_manager.delete_hash_field(hash_key, str(building_idx))
            
            if success:
                print(f"Removed cached building {building_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error removing cached building {building_idx} for user {user_no}: {e}")
            return False
    
    async def invalidate_building_cache(self, user_no: int) -> bool:
        """사용자 건물 캐시 전체 무효화"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self._get_buildings_meta_key(user_no)
            
            # 두 키 모두 삭제
            hash_deleted = await self.cache_manager.delete_data(hash_key)
            meta_deleted = await self.cache_manager.delete_data(meta_key)
            
            success = hash_deleted or meta_deleted
            if success:
                print(f"Cache invalidated for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    async def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅/모니터링용)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self._get_buildings_meta_key(user_no)
            
            # Cache Manager를 통해 정보 조회
            building_count = await self.cache_manager.get_hash_length(hash_key)
            ttl = await self.cache_manager.get_ttl(hash_key)
            meta_data = await self.cache_manager.get_data(meta_key) or {}
            
            return {
                "user_no": user_no,
                "building_count": building_count,
                "ttl_seconds": ttl,
                "meta_data": meta_data,
                "cache_exists": building_count > 0
            }
            
        except Exception as e:
            print(f"Error getting cache info for user {user_no}: {e}")
            return {"user_no": user_no, "cache_exists": False, "error": str(e)}
    
    async def update_cached_building_times(self, user_no: int, cached_buildings: Dict[str, Any]) -> Dict[str, Any]:
        """캐시된 건물들의 완료 시간을 실시간 업데이트 (필요시만 사용)"""
        try:
            updated_buildings = cached_buildings.copy()
            
            for building_idx, building_data in updated_buildings.items():
                # 진행 중인 건물들만 Task Manager에서 완료 시간 업데이트
                if building_data.get('status') in [1, 2]:
                    redis_completion_time = await self.get_building_completion_time(
                        user_no, int(building_idx)
                    )
                    if redis_completion_time:
                        building_data['end_time'] = redis_completion_time.isoformat()
                        building_data['updated_from_redis'] = True
                        
                        # 개별 건물 캐시도 업데이트
                        await self.update_cached_building(user_no, int(building_idx), building_data)
            
            return updated_buildings
            
        except Exception as e:
            print(f"Error updating building times from Redis: {e}")
            return cached_buildings
    
    
    
    # === 컴포넌트 접근 메서드들 (필요시 직접 접근) ===
    def get_task_manager(self) -> BaseRedisTaskManager:
        """Task Manager 컴포넌트 반환"""
        return self.task_manager
    
    def get_cache_manager(self) -> BaseRedisCacheManager:
        """Cache Manager 컴포넌트 반환"""
        return self.cache_manager
    
    # === 통합 유틸리티 메서드들 ===
    async def get_building_status(self, user_no: int, building_idx: int) -> Dict[str, Any]:
        """건물의 전체 상태 조회 (캐시 + 큐 정보)"""
        try:
            # 캐시에서 기본 정보 조회
            cached_building = await self.get_cached_building(user_no, building_idx)
            
            # 큐에서 완료 시간 조회
            completion_time = await self.get_building_completion_time(user_no, building_idx)
            
            status = {
                "building_idx": building_idx,
                "user_no": user_no,
                "cached_data": cached_building,
                "completion_time": completion_time.isoformat() if completion_time else None,
                "in_queue": completion_time is not None,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return status
            
        except Exception as e:
            print(f"Error getting building status for {building_idx}: {e}")
            return {
                "building_idx": building_idx,
                "user_no": user_no,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }