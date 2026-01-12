from typing import Dict, List, Any
# ResourceRedisManager를 import 목록에 추가합니다.
from services.redis_manager import BuildingRedisManager, UnitRedisManager, ResearchRedisManager, BuffRedisManager, ResourceRedisManager, ItemRedisManager, MissionRedisManager, ShopRedisManager
# ResourceRedisManager를 임포트한다고 가정합니다.

class RedisManager:
    """Redis 작업 관리자들의 중앙 접근점 (비동기 버전)"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        
        self._building_manager = None
        self._unit_manager = None
        self._research_manager = None
        self._buff_manager = None
        
        self._item_manager = None
        self._mission_manager = None
        self._resource_manager = None 
    
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
    
    # 🌟 ResourceRedisManager를 위한 게터 메서드를 추가합니다.
    def get_resource_manager(self) -> ResourceRedisManager:
        """자원 Redis 관리자 반환 (싱글톤 패턴)"""
        if self._resource_manager is None:
            self._resource_manager = ResourceRedisManager(self.redis_client)
        return self._resource_manager
    
    
    def get_item_manager(self) -> ItemRedisManager:
        """Item Redis 관리자 반환 (싱글톤 패턴)"""
        if self._item_manager is None:
            self._item_manager = ItemRedisManager(self.redis_client)
        return self._item_manager
    
    
    def get_mission_manager(self) -> MissionRedisManager:
        """Mission Redis 관리자 반환 (싱글톤 패턴)"""
        if self._mission_manager is None:
            self._mission_manager = MissionRedisManager(self.redis_client)
        return self._mission_manager
    
    def get_shop_manager(self) -> MissionRedisManager:
        """Mission Redis 관리자 반환 (싱글톤 패턴)"""
        if self._shop_manager is None:
            self._shop_manager = ShopRedisManager(self.redis_client)
        return self._shop_manager
    
    # --- 비동기 메서드 ---
    
    async def get_all_queue_status(self) -> Dict[str, Dict[str, int]]:
        """모든 큐의 상태를 조회 (관리자용)"""
        result = {}
        
        if self._building_manager:
            # get_task_manager()가 BuildingRedisManager에 있다고 가정
            result['building'] = await self._building_manager.get_task_manager().get_queue_status() 
        if self._unit_manager:
            result['unit_training'] = await self._unit_manager.get_queue_status()
        if self._research_manager:
            result['research'] = await self._research_manager.get_queue_status()
        if self._buff_manager:
            result['buff'] = await self._buff_manager.get_queue_status()
        # 🌟 Resource Manager는 보통 큐를 사용하지 않지만, 필요하다면 여기에 추가합니다.
        # if self._resource_manager:
        #     result['resource'] = await self._resource_manager.get_queue_status()
            
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
        # 🌟 Resource Manager는 작업 완료 개념이 없으므로 추가하지 않습니다.
            
        return result
    
    # ✅ 추가 필요한 메서드들

    async def hset(self, key, field, value):
        """Hash SET"""
        return await self.redis.hset(key, field, value)
    
    async def hgetall(self, key):
        """Hash GET ALL"""
        return await self.redis.hgetall(key)
    
    async def hdel(self, key, *fields):
        """Hash DELETE"""
        return await self.redis.hdel(key, *fields)
    
    async def hmset(self, key, mapping):
        """Hash MSET"""
        return await self.redis.hset(key, mapping=mapping)
    
    async def zadd(self, key, mapping):
        """Sorted Set ADD"""
        return await self.redis.zadd(key, mapping)
    
    async def zrangebyscore(self, key, min_score, max_score):
        """Sorted Set RANGE BY SCORE"""
        return await self.redis.zrangebyscore(key, min_score, max_score)
    
    async def zrem(self, key, *members):
        """Sorted Set REMOVE"""
        return await self.redis.zrem(key, *members)
    
    async def keys(self, pattern):
        """KEYS with pattern"""
        return await self.redis.keys(pattern)
    
    async def get(self, key):
        """GET"""
        return await self.redis.get(key)
    
    async def setex(self, key, seconds, value):
        """SET with expiry"""
        return await self.redis.setex(key, seconds, value)
    
    async def expire(self, key, seconds):
        """SET TTL"""
        return await self.redis.expire(key, seconds)
    
    async def delete(self, *keys):
        """DELETE"""
        return await self.redis.delete(*keys)