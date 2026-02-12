from datetime import datetime
from typing import Optional, List, Dict, Any
# 이 매니저들이 있는 곳과 동일한 위치에 있다고 가정하고 임포트합니다.
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager 
from .redis_types import CacheType, TaskType
import json


class ResearchRedisManager:
    """
    연구 전용 Redis 관리자 - Task Manager와 Cache Manager 컴포넌트 조합 (비동기 버전)
    BuildingRedisManager의 설계를 그대로 따릅니다.
    """
    
    def __init__(self, redis_client):
        # 두 개의 매니저 컴포넌트 초기화
        # TaskType과 CacheType은 RESEARCH로 변경
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.RESEARCH)
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.RESEARCH)
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간
    
    def validate_task_data(self, research_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """연구 데이터 유효성 검증"""
        return isinstance(research_idx, int) and research_idx > 0
    
    # === Task Manager 위임 메서드들 (연구 작업 큐 관리) ===
    
    async def add_research_to_queue(self, user_no: int, research_idx: int, completion_time: datetime) -> bool:
        """연구를 완료 큐에 추가 (building_redis_manager.add_building_to_queue 미러링)"""
        if not self.validate_task_data(research_idx):
            return False
        return await self.task_manager.add_to_queue(user_no, research_idx, completion_time)
    
    async def remove_research_from_queue(self, user_no: int, research_idx: int) -> bool:
        """연구를 완료 큐에서 제거 (building_redis_manager.remove_building_from_queue 미러링)"""
        return await self.task_manager.remove_from_queue(user_no, research_idx)
    
    async def get_research_completion_time(self, user_no: int, research_idx: int) -> Optional[datetime]:
        """연구 완료 시간 조회"""
        return await self.task_manager.get_completion_time(user_no, research_idx)
    
    async def update_research_completion_time(self, user_no: int, research_idx: int, new_completion_time: datetime) -> bool:
        """연구 완료 시간 업데이트 (building_redis_manager.update_building_completion_time 미러링)"""
        return await self.task_manager.update_completion_time(user_no, research_idx, new_completion_time)
    
    async def get_completed_research(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 연구들 조회"""
        return await self.task_manager.get_completed_tasks(current_time)
    
    async def speedup_research(self, user_no: int, research_idx: int) -> bool:
        """연구 즉시 완료"""
        return await self.task_manager.update_completion_time(user_no, research_idx, datetime.utcnow())
    
    # === Hash 기반 캐싱 관리 메서드들 (연구 데이터 캐싱) ===
    
    async def cache_user_researches_data(self, user_no: int, research_data: Dict[str, Any]) -> bool:
        """Hash 구조로 연구 데이터 캐싱 (building_redis_manager.cache_user_buildings_data 미러링)"""
        if not research_data:
            return True
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'research_count': len(research_data),
                'user_no': user_no
            }
            
            # Cache Manager를 통해 Hash 형태로 저장
            success = await self.cache_manager.set_hash_data(
                hash_key, 
                research_data, 
                expire_time=self.cache_expire_time
            )
            
            if success:
                # 메타데이터도 저장
                await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
                print(f"Successfully cached {len(research_data)} researches for user {user_no} using Hash")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error caching research data: {e}")
            return False
    
    async def get_cached_research(self, user_no: int, research_idx: int) -> Optional[Dict[str, Any]]:
        """특정 연구 하나만 캐시에서 조회 (building_redis_manager.get_cached_building 미러링)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            research_data = await self.cache_manager.get_hash_field(hash_key, str(research_idx))
            
            if research_data:
                print(f"Cache hit: Retrieved research {research_idx} for user {user_no}")
                return research_data
            
            print(f"Cache miss: Research {research_idx} not found for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached research {research_idx} for user {user_no}: {e}")
            return None
    
    async def get_cached_researches(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 연구를 캐시에서 조회 (building_redis_manager.get_cached_buildings 미러링)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            researchs = await self.cache_manager.get_hash_data(hash_key)
            
            if researchs:
                print(f"Cache hit: Retrieved {len(researchs)} researches for user {user_no}")
                return researchs
            
            print(f"Cache miss: No cached researches for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached researches for user {user_no}: {e}")
            return None
    
    async def update_cached_research(self, user_no: int, research_idx: int, research_data: Dict[str, Any]) -> bool:
        """특정 연구 캐시 업데이트 (building_redis_manager.update_cached_building 미러링)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # Cache Manager를 통해 Hash 필드 업데이트
            success = await self.cache_manager.set_hash_field(
                hash_key, 
                str(research_idx), 
                research_data,
                expire_time=self.cache_expire_time
            )
            
            if success:
                self.redis_client.sadd("sync_pending:research", str(user_no))
                print(f"Updated cached research {research_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error updating cached research {research_idx} for user {user_no}: {e}")
            return False
    
    async def remove_cached_research(self, user_no: int, research_idx: int) -> bool:
        """특정 연구를 캐시에서 제거 (building_redis_manager.remove_cached_building 미러링)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            success = await self.cache_manager.delete_hash_field(hash_key, str(research_idx))
            
            if success:
                print(f"Removed cached research {research_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error removing cached research {research_idx} for user {user_no}: {e}")
            return False
    
    async def invalidate_research_cache(self, user_no: int) -> bool:
        """사용자 연구 캐시 전체 무효화 (building_redis_manager.invalidate_building_cache 미러링)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 두 키 모두 삭제
            hash_deleted = await self.cache_manager.delete_data(hash_key)
            meta_deleted = await self.cache_manager.delete_data(meta_key)
            
            success = hash_deleted or meta_deleted
            if success:
                print(f"Research cache invalidated for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error invalidating research cache for user {user_no}: {e}")
            return False
    
    async def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅/모니터링용 - building_redis_manager.get_cache_info 미러링)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # Cache Manager를 통해 정보 조회
            research_count = await self.cache_manager.get_hash_length(hash_key)
            ttl = await self.cache_manager.get_ttl(hash_key)
            meta_data = await self.cache_manager.get_data(meta_key) or {}
            
            return {
                "user_no": user_no,
                "research_count": research_count,
                "ttl_seconds": ttl,
                "meta_data": meta_data,
                "cache_exists": research_count > 0
            }
            
        except Exception as e:
            print(f"Error getting research cache info for user {user_no}: {e}")
            return {"user_no": user_no, "cache_exists": False, "error": str(e)}
            
    async def update_cached_research_times(self, user_no: int, cached_researchs: Dict[str, Any]) -> Dict[str, Any]:
        """캐시된 연구들의 완료 시간을 실시간 업데이트 (building_redis_manager.update_cached_building_times 미러링)"""
        try:
            updated_researchs = cached_researchs.copy()
            
            for research_idx, research_data in updated_researchs.items():
                # 진행 중인 연구들만 Task Manager에서 완료 시간 업데이트
                # 'status' 필드에 대한 가정이 필요합니다. building_redis_manager의 로직을 따릅니다.
                if research_data.get('status') in [1, 2]:
                    redis_completion_time = await self.get_research_completion_time(
                        user_no, int(research_idx)
                    )
                    if redis_completion_time:
                        research_data['end_time'] = redis_completion_time.isoformat()
                        research_data['updated_from_redis'] = True
                        
                        # 개별 연구 캐시도 업데이트
                        await self.update_cached_research(user_no, int(research_idx), research_data)
            
            return updated_researchs
            
        except Exception as e:
            print(f"Error updating research times from Redis: {e}")
            return cached_researchs
    
    # === 통합 유틸리티 메서드들 ===
    async def get_research_status(self, user_no: int, research_idx: int) -> Dict[str, Any]:
        """연구의 전체 상태 조회 (캐시 + 큐 정보 - building_redis_manager.get_building_status 미러링)"""
        try:
            # 캐시에서 기본 정보 조회
            cached_research = await self.get_cached_research(user_no, research_idx)
            
            # 큐에서 완료 시간 조회
            completion_time = await self.get_research_completion_time(user_no, research_idx)
            
            status = {
                "research_idx": research_idx,
                "user_no": user_no,
                "cached_data": cached_research,
                "completion_time": completion_time.isoformat() if completion_time else None,
                "in_queue": completion_time is not None,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return status
            
        except Exception as e:
            print(f"Error getting research status for {research_idx}: {e}")
            return {
                "research_idx": research_idx,
                "user_no": user_no,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    # === 진행 중인 연구 관리 (O(1) 조회) ===
    
    def _get_ongoing_key(self, user_no: int) -> str:
        """진행 중인 연구 키"""
        return f"user_data:{user_no}:research_ongoing"
    
    async def set_ongoing_research(self, user_no: int, research_idx: int, end_time: datetime) -> bool:
        """진행 중인 연구 설정"""
        try:
            key = self._get_ongoing_key(user_no)
            data = {
                'research_idx': research_idx,
                'end_time': end_time.isoformat()
            }
            success = await self.cache_manager.set_data(key, data, expire_time=self.cache_expire_time)
            if success:
                print(f"Set ongoing research {research_idx} for user {user_no}")
            return success
        except Exception as e:
            print(f"Error setting ongoing research for user {user_no}: {e}")
            return False
    
    async def get_ongoing_research(self, user_no: int) -> Optional[Dict[str, Any]]:
        """진행 중인 연구 조회 - O(1)"""
        try:
            key = self._get_ongoing_key(user_no)
            return await self.cache_manager.get_data(key)
        except Exception as e:
            print(f"Error getting ongoing research for user {user_no}: {e}")
            return None
    
    async def clear_ongoing_research(self, user_no: int) -> bool:
        """진행 중인 연구 클리어 (완료 시)"""
        try:
            key = self._get_ongoing_key(user_no)
            success = await self.cache_manager.delete_data(key)
            if success:
                print(f"Cleared ongoing research for user {user_no}")
            return success
        except Exception as e:
            print(f"Error clearing ongoing research for user {user_no}: {e}")
            return False
    
    async def has_ongoing_research(self, user_no: int) -> bool:
        """진행 중인 연구 있는지 확인 - O(1)"""
        ongoing = await self.get_ongoing_research(user_no)
        return ongoing is not None
    
    # === 별칭 메서드 (ResearchManager 호환용) ===
    async def invalidate_cache(self, user_no: int) -> bool:
        """invalidate_research_cache의 별칭 (ResearchManager 호환)"""
        return await self.invalidate_research_cache(user_no)
            
    # === 컴포넌트 접근 메서드들 (필요시 직접 접근) ===
    def get_task_manager(self) -> BaseRedisTaskManager:
        """Task Manager 컴포넌트 반환"""
        return self.task_manager
    
    def get_cache_manager(self) -> BaseRedisCacheManager:
        """Cache Manager 컴포넌트 반환"""
        return self.cache_manager