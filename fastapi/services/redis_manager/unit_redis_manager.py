from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_manager import BaseRedisTaskManager
from .task_types import TaskType

class UnitRedisManager(BaseRedisTaskManager):
    """유닛 훈련 전용 Redis 관리자"""
    
    def __init__(self, redis_client):
        super().__init__(redis_client, TaskType.UNIT_TRAINING)
    
    def validate_task_data(self, unit_type: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """유닛 데이터 유효성 검증"""
        if not isinstance(unit_type, int) or unit_type <= 0:
            return False
        if metadata and 'unit_count' in metadata:
            try:
                count = int(metadata['unit_count'])
                return count > 0
            except (ValueError, TypeError):
                return False
        return True
    
    def add_unit_training(self, user_no: int, unit_type: int, completion_time: datetime,
                         queue_id: Optional[int] = None, unit_count: int = 1) -> bool:
        """유닛 훈련을 큐에 추가"""
        metadata = {'unit_count': str(unit_count)}
        if not self.validate_task_data(unit_type, metadata):
            return False
        return self.add_to_queue(user_no, unit_type, completion_time, queue_id, metadata)
    
    def remove_unit_training(self, user_no: int, unit_type: int, queue_id: Optional[int] = None) -> bool:
        """유닛 훈련을 큐에서 제거"""
        return self.remove_from_queue(user_no, unit_type, queue_id)
    
    def get_unit_completion_time(self, user_no: int, unit_type: int, queue_id: Optional[int] = None) -> Optional[datetime]:
        """유닛 훈련 완료 시간 조회"""
        return self.get_completion_time(user_no, unit_type, queue_id)
    
    def get_completed_units(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 유닛 훈련들 조회"""
        return self.get_completed_tasks(current_time)
    
    def speedup_unit_training(self, user_no: int, unit_type: int, queue_id: Optional[int] = None) -> bool:
        """유닛 훈련 즉시 완료"""
        return self.update_completion_time(user_no, unit_type, datetime.utcnow(), queue_id)