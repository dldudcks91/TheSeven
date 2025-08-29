from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from .base_redis_manager import BaseRedisTaskManager
from .task_types import TaskType
import json
import models

class BuildingRedisManager(BaseRedisTaskManager):
    """건물 전용 Redis 관리자 - 직접 캐싱"""
    
    def __init__(self, redis_client):
        super().__init__(redis_client, TaskType.BUILDING)
        self.cache_expire_time = 3600  # 1시간
    
    def validate_task_data(self, building_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """건물 데이터 유효성 검증"""
        return isinstance(building_idx, int) and building_idx > 0
    
    def add_building_to_queue(self, user_no: int, building_idx: int, completion_time: datetime) -> bool:
        """건물을 큐에 추가"""
        if not self.validate_task_data(building_idx):
            return False
        return self.add_to_queue(user_no, building_idx, completion_time)
    
    def remove_building_from_queue(self, user_no: int, building_idx: int) -> bool:
        """건물을 큐에서 제거"""
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
    
    def _get_cache_key(self, user_no: int) -> str:
        """캐시 키 생성"""
        return f"user_buildings:{user_no}"
    
    def cache_user_buildings(self, user_no: int, db: Session, building_manager=None) -> Dict[str, Any]:
        """사용자 건물 데이터 캐싱"""
        try:
            if not building_manager:
                from services.building_manager import BuildingManager
                building_manager = BuildingManager(db, self)
            
            buildings = building_manager._get_all_user_buildings(user_no)
            
            buildings_data = {}
            for building in buildings:
                buildings_data[building.building_idx] = building_manager._format_building_data(building)
            
            # Redis에 직접 저장
            cache_key = self._get_cache_key(user_no)
            cache_data = {
                'buildings': buildings_data,
                'cached_at': datetime.utcnow().isoformat(),
                'user_no': user_no
            }
            
            self.redis.setex(cache_key, self.cache_expire_time, json.dumps(cache_data, default=str))
            
            print(f"Cached buildings for user {user_no}: {len(buildings_data)} buildings")
            return {"success": True, "count": len(buildings_data)}
            
        except Exception as e:
            print(f"Error caching buildings for user {user_no}: {e}")
            return {"success": False, "count": 0}
    
    def get_cached_buildings(self, user_no: int) -> Optional[Dict[str, Any]]:
        """캐시에서 건물 데이터 조회"""
        try:
            cache_key = self._get_cache_key(user_no)
            cached_data = self.redis.get(cache_key)
            
            if cached_data:
                data = json.loads(cached_data)
                print(f"Retrieved cached buildings for user {user_no}")
                return data.get('buildings', {})
            
            return None
            
        except Exception as e:
            print(f"Error retrieving cached buildings for user {user_no}: {e}")
            return None
    
    def update_building_cache(self, user_no: int, building_idx: int, building_data: Dict[str, Any]) -> bool:
        """캐시에서 특정 건물 업데이트"""
        try:
            cached_buildings = self.get_cached_buildings(user_no)
            if cached_buildings is None:
                return False
            
            cached_buildings[str(building_idx)] = building_data
            
            # 전체 캐시 다시 저장
            cache_key = self._get_cache_key(user_no)
            cache_data = {
                'buildings': cached_buildings,
                'cached_at': datetime.utcnow().isoformat(),
                'user_no': user_no
            }
            
            self.redis.setex(cache_key, self.cache_expire_time, json.dumps(cache_data, default=str))
            return True
            
        except Exception as e:
            print(f"Error updating building {building_idx} in cache for user {user_no}: {e}")
            return False
    
    def invalidate_building_cache(self, user_no: int) -> bool:
        """건물 캐시 무효화"""
        try:
            cache_key = self._get_cache_key(user_no)
            result = self.redis.delete(cache_key)
            print(f"Invalidated cache for user {user_no}")
            return result > 0
            
        except Exception as e:
            print(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    def sync_buildings_to_redis(self, user_no: int, db: Session):
        """진행 중인 건물을 Redis에 동기화"""
        try:
            active_buildings = db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.status.in_([1, 2]),
                models.Building.end_time.isnot(None)
            ).all()
            
            for building in active_buildings:
                existing_time = self.get_building_completion_time(
                    user_no, building.building_idx
                )
                
                if not existing_time:
                    self.add_building_to_queue(
                        user_no, building.building_idx, building.end_time
                    )
                    print(f"Synced building {building.building_idx} to Redis queue")
                    
        except Exception as e:
            print(f"Error syncing buildings to Redis: {e}")
    
    def get_buildings_with_cache(self, user_no: int, db: Session, building_manager=None) -> Dict[str, Any]:
        """캐시 우선 조회로 건물 정보 반환"""
        try:
            # 1. 캐시에서 먼저 조회
            cached_buildings = self.get_cached_buildings(user_no)
            
            if cached_buildings:
                # Redis에서 진행 중인 건물들의 완료 시간 업데이트
                updated_buildings = self._update_building_times_from_redis(user_no, cached_buildings)
                return {
                    "success": True,
                    "message": f"Retrieved {len(updated_buildings)} buildings from cache",
                    "data": updated_buildings,
                    "source": "cache"
                }
            
            # 2. 캐시 미스시 BuildingManager로부터 데이터 로드 후 캐싱
            cache_result = self.cache_user_buildings(user_no, db, building_manager)
            
            if cache_result.get("success"):
                cached_buildings = self.get_cached_buildings(user_no)
                return {
                    "success": True,
                    "message": f"Retrieved {cache_result['count']} buildings from database",
                    "data": cached_buildings or {},
                    "source": "database"
                }
            
            return {"success": False, "message": "Failed to load building data", "data": {}}
            
        except Exception as e:
            print(f"Error getting buildings with cache: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    def _update_building_times_from_redis(self, user_no: int, cached_buildings: Dict[str, Any]) -> Dict[str, Any]:
        """캐시된 건물들의 완료 시간을 Redis에서 실시간 업데이트"""
        try:
            for building_idx, building_data in cached_buildings.items():
                if building_data.get('status') in [1, 2]:  # 진행 중인 건물
                    redis_completion_time = self.get_building_completion_time(
                        user_no, int(building_idx)
                    )
                    if redis_completion_time:
                        building_data['end_time'] = redis_completion_time.isoformat()
            
            return cached_buildings
            
        except Exception as e:
            print(f"Error updating building times from Redis: {e}")
            return cached_buildings