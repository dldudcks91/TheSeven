from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_manager import BaseRedisTaskManager
from .task_types import TaskType

class BuffRedisManager(BaseRedisTaskManager):
    """버프 전용 Redis 관리자"""
    
    def __init__(self, redis_client):
        super().__init__(redis_client, TaskType.BUFF)
    
    def validate_task_data(self, buff_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """버프 데이터 유효성 검증"""
        return isinstance(buff_idx, int) and buff_idx > 0
    
    def add_buff(self, user_no: int, buff_idx: int, completion_time: datetime, 
                 buff_type: Optional[int] = None, target_no: Optional[int] = None) -> bool:
        """버프를 큐에 추가"""
        if not self.validate_task_data(buff_idx):
            return False
        
        metadata = {}
        if buff_type is not None:
            metadata['buff_type'] = str(buff_type)
        if target_no is not None:
            metadata['target_no'] = str(target_no)
            
        return self.add_to_queue(user_no, buff_idx, completion_time, metadata=metadata)
    
    def remove_buff(self, user_no: int, buff_idx: int) -> bool:
        """버프를 큐에서 제거"""
        return self.remove_from_queue(user_no, buff_idx)
    
    def get_buff_completion_time(self, user_no: int, buff_idx: int) -> Optional[datetime]:
        """버프 완료 시간 조회"""
        return self.get_completion_time(user_no, buff_idx)
    
    def update_buff_completion_time(self, user_no: int, buff_idx: int, new_completion_time: datetime) -> bool:
        """버프 완료 시간 업데이트"""
        return self.update_completion_time(user_no, buff_idx, new_completion_time)
    
    def get_completed_buffs(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 버프들 조회"""
        return self.get_completed_tasks(current_time)
    
    def speedup_buff(self, user_no: int, buff_idx: int) -> bool:
        """버프 즉시 완료"""
        return self.update_completion_time(user_no, buff_idx, datetime.utcnow())