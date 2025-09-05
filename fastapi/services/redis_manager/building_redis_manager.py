from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_manager import BaseRedisTaskManager
from .task_types import TaskType
import json

class BuildingRedisManager(BaseRedisTaskManager):
    """건물 전용 Redis 관리자 - Hash 기반 효율적 캐싱"""
    
    def __init__(self, redis_client):
        super().__init__(redis_client, TaskType.BUILDING)
        self.cache_expire_time = 3600  # 1시간
    
    def validate_task_data(self, building_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """건물 데이터 유효성 검증"""
        return isinstance(building_idx, int) and building_idx > 0
    
    # === 완료 큐 관리 메서드들 ===
    def add_building_to_queue(self, user_no: int, building_idx: int, completion_time: datetime) -> bool:
        """건물을 완료 큐에 추가"""
        if not self.validate_task_data(building_idx):
            return False
        return self.add_to_queue(user_no, building_idx, completion_time)
    
    def remove_building_from_queue(self, user_no: int, building_idx: int) -> bool:
        """건물을 완료 큐에서 제거"""
        return self.remove_from_queue(user_no, building_idx)
    
    def get_building_completion_time(self, user_no: int, building_idx: int) -> Optional[datetime]:
        """건물 완료 시간 조회"""
        return self.get_completion_time(user_no, building_idx)
    
    def update_building_completion_time(self, user_no: int, building_idx: int, new_completion_time: datetime) -> bool:
        """건물 완료 시간 업데이트"""
        return self.update_completion_time(user_no, building_idx, new_completion_time)
    
    def get_completed_buildings(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 건물들 조회"""
        return self.get_completed_tasks(current_time)
    
    def speedup_building(self, user_no: int, building_idx: int) -> bool:
        """건물 즉시 완료"""
        return self.update_completion_time(user_no, building_idx, datetime.utcnow())
    
    # === Hash 기반 캐싱 관리 메서드들 ===
    def _get_buildings_hash_key(self, user_no: int) -> str:
        """사용자 건물 Hash 키 생성"""
        return f"user_buildings:{user_no}"
    
    def _get_buildings_meta_key(self, user_no: int) -> str:
        """사용자 건물 메타데이터 키 생성"""
        return f"user_buildings_meta:{user_no}"
    
    def cache_user_buildings_data(self, user_no: int, buildings_data: Dict[str, Any]) -> bool:
        """Hash 구조로 건물 데이터 캐싱"""
        if not buildings_data:
            return True
            
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            meta_key = self._get_buildings_meta_key(user_no)
            
            pipeline = self.redis_client.pipeline()
            
            # 기존 Hash 데이터 삭제
            pipeline.delete(hash_key)
            
            # 각 건물을 Hash 필드로 저장
            for building_idx, building_data in buildings_data.items():
                pipeline.hset(hash_key, building_idx, json.dumps(building_data, default=str))
            
            # 메타데이터 저장 (캐시 시간, 건물 개수 등)
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'building_count': len(buildings_data),
                'user_no': user_no
            }
            pipeline.set(meta_key, json.dumps(meta_data))
            
            # TTL 설정
            pipeline.expire(hash_key, self.cache_expire_time)
            pipeline.expire(meta_key, self.cache_expire_time)
            
            pipeline.execute()
            
            print(f"Successfully cached {len(buildings_data)} buildings for user {user_no} using Hash")
            return True
            
        except Exception as e:
            print(f"Error caching buildings data: {e}")
            return False
    
    def get_cached_building(self, user_no: int, building_idx: int) -> Optional[Dict[str, Any]]:
        """특정 건물 하나만 캐시에서 조회"""
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            building_data = self.redis_client.hget(hash_key, str(building_idx))
            
            if building_data:
                print(f"Cache hit: Retrieved building {building_idx} for user {user_no}")
                return json.loads(building_data)
            
            print(f"Cache miss: Building {building_idx} not found for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached building {building_idx} for user {user_no}: {e}")
            return None
    
    def get_cached_buildings(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 건물을 캐시에서 조회"""
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            
            # Hash의 모든 필드 조회
            cached_data = self.redis_client.hgetall(hash_key)
            
            if cached_data:
                buildings = {}
                for building_idx, building_data in cached_data.items():
                    # Redis에서 받은 bytes를 string으로 변환
                    if isinstance(building_idx, bytes):
                        building_idx = building_idx.decode('utf-8')
                    if isinstance(building_data, bytes):
                        building_data = building_data.decode('utf-8')
                    
                    buildings[building_idx] = json.loads(building_data)
                
                print(f"Cache hit: Retrieved {len(buildings)} buildings for user {user_no}")
                return buildings
            
            print(f"Cache miss: No cached buildings for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached buildings for user {user_no}: {e}")
            return None
    
    def update_cached_building(self, user_no: int, building_idx: int, building_data: Dict[str, Any]) -> bool:
        """특정 건물 캐시 업데이트"""
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            
            # Hash에서 해당 건물 필드만 업데이트
            result = self.redis_client.hset(
                hash_key, 
                str(building_idx), 
                json.dumps(building_data, default=str)
            )
            
            # TTL 갱신
            self.redis_client.expire(hash_key, self.cache_expire_time)
            
            print(f"Updated cached building {building_idx} for user {user_no}")
            return bool(result)
            
        except Exception as e:
            print(f"Error updating cached building {building_idx} for user {user_no}: {e}")
            return False
    
    def remove_cached_building(self, user_no: int, building_idx: int) -> bool:
        """특정 건물을 캐시에서 제거"""
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            result = self.redis_client.hdel(hash_key, str(building_idx))
            
            print(f"Removed cached building {building_idx} for user {user_no}")
            return result > 0
            
        except Exception as e:
            print(f"Error removing cached building {building_idx} for user {user_no}: {e}")
            return False
    
    def invalidate_building_cache(self, user_no: int) -> bool:
        """사용자 건물 캐시 전체 무효화"""
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            meta_key = self._get_buildings_meta_key(user_no)
            
            pipeline = self.redis_client.pipeline()
            pipeline.delete(hash_key)
            pipeline.delete(meta_key)
            results = pipeline.execute()
            
            deleted_count = sum(results)
            if deleted_count > 0:
                print(f"Cache invalidated for user {user_no}")
            
            return deleted_count > 0
            
        except Exception as e:
            print(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅/모니터링용)"""
        try:
            hash_key = self._get_buildings_hash_key(user_no)
            meta_key = self._get_buildings_meta_key(user_no)
            
            pipeline = self.redis_client.pipeline()
            pipeline.hlen(hash_key)  # Hash 크기
            pipeline.ttl(hash_key)   # TTL
            pipeline.get(meta_key)   # 메타데이터
            results = pipeline.execute()
            
            building_count = results[0] or 0
            ttl = results[1] or -1
            meta_data = json.loads(results[2]) if results[2] else {}
            
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
    
    def update_cached_building_times(self, user_no: int, cached_buildings: Dict[str, Any]) -> Dict[str, Any]:
        """캐시된 건물들의 완료 시간을 실시간 업데이트 (필요시만 사용)"""
        try:
            updated_buildings = cached_buildings.copy()
            
            for building_idx, building_data in updated_buildings.items():
                # 진행 중인 건물들만 Redis 큐에서 완료 시간 업데이트
                if building_data.get('status') in [1, 2]:
                    redis_completion_time = self.get_building_completion_time(
                        user_no, int(building_idx)
                    )
                    if redis_completion_time:
                        building_data['end_time'] = redis_completion_time.isoformat()
                        building_data['updated_from_redis'] = True
                        
                        # 개별 건물 캐시도 업데이트
                        self.update_cached_building(user_no, int(building_idx), building_data)
            
            return updated_buildings
            
        except Exception as e:
            print(f"Error updating building times from Redis: {e}")
            return cached_buildings