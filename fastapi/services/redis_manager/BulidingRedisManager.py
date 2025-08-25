
from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_manager import BaseRedisTaskManager
from .task_types import TaskType

class BuildingRedisManager(BaseRedisTaskManager):
    """건물 전용 Redis 관리자"""
    
    def __init__(self, redis_client):
        super().__init__(redis_client, TaskType.BUILDING)
    
    def validate_task_data(self, building_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """건물 데이터 유효성 검증"""
        return isinstance(building_idx, int) and building_idx > 0
    
    def add_building(self, user_no: int, building_idx: int, completion_time: datetime) -> bool:
        """건물을 큐에 추가"""
        if not self.validate_task_data(building_idx):
            return False
        return self.add_to_queue(user_no, building_idx, completion_time)
    
    def remove_building(self, user_no: int, building_idx: int) -> bool:
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