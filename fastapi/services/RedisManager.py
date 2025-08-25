from datetime import datetime
from typing import Optional, List, Dict, Any
from .building_redis_manager import BuildingRedisManager
from .unit_redis_manager import UnitRedisManager
from .research_redis_manager import ResearchRedisManager

from enum import Enum

class TaskType(Enum):
    """작업 타입 정의"""
    BUILDING = "building"
    UNIT_TRAINING = "unit_training"  
    RESEARCH = "research"
    HEALING = "healing"
    GATHERING = "gathering"
    
class RedisTaskManagerFactory:
    """Redis 작업 관리자들을 생성하고 관리하는 팩토리"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self._managers = {}
    
    def get_building_manager(self) -> BuildingRedisManager:
        """건물 관리자 반환"""
        if 'building' not in self._managers:
            self._managers['building'] = BuildingRedisManager(self.redis_client)
        return self._managers['building']
    
    def get_unit_manager(self) -> UnitRedisManager:
        """유닛 관리자 반환"""
        if 'unit' not in self._managers:
            self._managers['unit'] = UnitRedisManager(self.redis_client)
        return self._managers['unit']
    
    def get_research_manager(self) -> ResearchRedisManager:
        """연구 관리자 반환"""
        if 'research' not in self._managers:
            self._managers['research'] = ResearchRedisManager(self.redis_client)
        return self._managers['research']
    
    def get_all_completed_tasks(self) -> Dict[str, List[Dict[str, Any]]]:
        """모든 타입의 완료된 작업들을 조회"""
        result = {}
        for task_type, manager in self._managers.items():
            result[task_type] = manager.get_completed_tasks()
        return result
    
    def get_all_queue_status(self) -> Dict[str, Dict[str, int]]:
        """모든 큐의 상태를 조회"""
        result = {}
        for task_type, manager in self._managers.items():
            result[task_type] = manager.get_queue_status()
        return result

class RedisManager:
    """기존 코드와의 호환성을 위한 래퍼 클래스"""
    
    def __init__(self, redis_client):
        self.factory = RedisTaskManagerFactory(redis_client)
        self._building_manager = self.factory.get_building_manager()
    
    # 건물 관련 메소드들 (기존 BuildingManager 호환성)
    def add_building_to_queue(self, user_no: int, building_idx: int, completion_time: datetime) -> bool:
        return self._building_manager.add_building(user_no, building_idx, completion_time)
    
    def get_building_completion_time(self, user_no: int, building_idx: int) -> Optional[datetime]:
        return self._building_manager.get_building_completion_time(user_no, building_idx)
    
    def update_building_completion_time(self, user_no: int, building_idx: int, new_completion_time: datetime) -> bool:
        return self._building_manager.update_building_completion_time(user_no, building_idx, new_completion_time)
    
    def remove_building_from_queue(self, user_no: int, building_idx: int) -> bool:
        return self._building_manager.remove_building(user_no, building_idx)
    
    def get_completed_buildings(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        return self._building_manager.get_completed_buildings(current_time)
    
    # 팩토리 접근 메소드들
    def get_building_manager(self) -> BuildingRedisManager:
        return self.factory.get_building_manager()
    
    def get_unit_manager(self) -> UnitRedisManager:
        return self.factory.get_unit_manager()
    
    def get_research_manager(self) -> ResearchRedisManager:
        return self.factory.get_research_manager()
    
    def get_all_queue_status(self) -> Dict[str, Dict[str, int]]:
        return self.factory.get_all_queue_status()