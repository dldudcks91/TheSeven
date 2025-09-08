from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .task_types import TaskType

class ResearchRedisManager(BaseRedisTaskManager):
    """연구 전용 Redis 관리자"""
    
    def __init__(self, redis_client):
        super().__init__(redis_client, TaskType.RESEARCH)
    
    def validate_task_data(self, research_id: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """연구 데이터 유효성 검증"""
        return isinstance(research_id, int) and research_id > 0
    
    def add_research(self, user_no: int, research_id: int, completion_time: datetime) -> bool:
        """연구를 큐에 추가"""
        if not self.validate_task_data(research_id):
            return False
        return self.add_to_queue(user_no, research_id, completion_time)
    
    def remove_research(self, user_no: int, research_id: int) -> bool:
        """연구를 큐에서 제거"""
        return self.remove_from_queue(user_no, research_id)
    
    def get_research_completion_time(self, user_no: int, research_id: int) -> Optional[datetime]:
        """연구 완료 시간 조회"""
        return self.get_completion_time(user_no, research_id)
    
    def get_completed_research(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 연구들 조회"""
        return self.get_completed_tasks(current_time)
    
    def speedup_research(self, user_no: int, research_id: int) -> bool:
        """연구 즉시 완료"""
        return self.update_completion_time(user_no, research_id, datetime.utcnow())