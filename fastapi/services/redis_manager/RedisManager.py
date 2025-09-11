from typing import Dict, List, Any
from services.redis_manager import BuildingRedisManager, UnitRedisManager, ResearchRedisManager, BuffRedisManager

class RedisManager:
    """Redis 작업 관리자들의 중앙 접근점 (비동기 버전)"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self._building_manager = None
        self._unit_manager = None
        self._research_manager = None
        self._buff_manager = None
    
    def get_building_manager(self) -> BuildingRedisManager:
        """건물 Redis 관리자 반환 (싱글톤 패턴)"""
        if self._building_manager is None:
            self._building_manager = BuildingRedisManager(self.redis_client)
        return self._building_manager
    
    def get_unit_manager(self) -> UnitRedisManager:
        """유닛 Redis 관리자 반환 (싱글톤 패턴)"""
        if self._unit_manager is None:
            self._unit_manager = UnitRedisManager(self.redis_client)
        return self._unit_manager
    
    def get_research_manager(self) -> ResearchRedisManager:
        """연구 Redis 관리자 반환 (싱글톤 패턴)"""
        if self._research_manager is None:
            self._research_manager = ResearchRedisManager(self.redis_client)
        return self._research_manager
    
    def get_buff_manager(self) -> BuffRedisManager:
        """버프 Redis 관리자 반환 (싱글톤 패턴)"""
        if self._buff_manager is None:
            self._buff_manager = BuffRedisManager(self.redis_client)
        return self._buff_manager
    
    async def get_all_queue_status(self) -> Dict[str, Dict[str, int]]:
        """모든 큐의 상태를 조회 (관리자용)"""
        result = {}
        
        if self._building_manager:
            result['building'] = await self._building_manager.get_task_manager().get_queue_status()
        if self._unit_manager:
            result['unit_training'] = await self._unit_manager.get_queue_status()
        if self._research_manager:
            result['research'] = await self._research_manager.get_queue_status()
        if self._buff_manager:
            result['buff'] = await self._buff_manager.get_queue_status()
            
        return result
    
    async def get_all_completed_tasks(self) -> Dict[str, List[Dict[str, Any]]]:
        """모든 타입의 완료된 작업들을 조회 (백그라운드 워커용)"""
        result = {}
        
        if self._building_manager:
            result['building'] = await self._building_manager.get_completed_buildings()
        if self._unit_manager:
            result['unit_training'] = await self._unit_manager.get_completed_units()
        if self._research_manager:
            result['research'] = await self._research_manager.get_completed_research()
        if self._buff_manager:
            result['buff'] = await self._buff_manager.get_completed_buffs()
            
        return result