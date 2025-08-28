# services/comprehensive_login_service.py
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import models
from .game_data_cache_manager import GameDataCacheManager
from .redis_manager import RedisManager

class LoginManager:
    """통합 사용자 로그인 서비스"""
    
    def __init__(self, db: Session, redis_manager: RedisManager):
        self.db = db
        self.redis_manager = redis_manager
        self.cache_manager = GameDataCacheManager(redis_manager)
    
    def handle_user_login(self, user_no: int) -> Dict[str, Any]:
        """사용자 로그인 처리 (모든 게임 데이터 캐싱)"""
        try:
            # 캐시 유효성 확인
            if self._is_user_cache_valid(user_no):
                return {"success": True, "message": "Using cached data", "source": "cache"}
            
            # 모든 게임 데이터 로드 및 캐싱
            cache_results = {}
            
            # 1. 건물 데이터 캐싱
            buildings_result = self._cache_user_buildings(user_no)
            cache_results['buildings'] = buildings_result
            
            # 2. 유닛 데이터 캐싱
            units_result = self._cache_user_units(user_no)
            cache_results['units'] = units_result
            
            # 3. 연구 데이터 캐싱
            research_result = self._cache_user_research(user_no)
            cache_results['research'] = research_result
            
            # 4. 자원 데이터 캐싱
            resources_result = self._cache_user_resources(user_no)
            cache_results['resources'] = resources_result
            
            # 5. 버프 데이터 캐싱
            buffs_result = self._cache_user_buffs(user_no)
            cache_results['buffs'] = buffs_result
            
            # 6. 진행 중인 작업들 Redis 동기화
            self._sync_active_tasks_to_redis(user_no)
            
            # 결과 집계
            total_items = sum(result.get('count', 0) for result in cache_results.values())
            
            return {
                "success": True,
                "message": f"Login processed. Cached {total_items} total items",
                "cache_results": cache_results,
                "source": "database"
            }
            
        except Exception as e:
            print(f"Error in comprehensive login processing for user {user_no}: {e}")
            return {"success": False, "message": str(e)}
    
    def _is_user_cache_valid(self, user_no: int, max_age_minutes: int = 30) -> bool:
        """사용자의 모든 캐시가 유효한지 확인"""
        for data_type in self.cache_manager.cache_prefixes.keys():
            if not self.cache_manager.get_cached_data(user_no, data_type):
                return False
        return True
    
    def _cache_user_buildings(self, user_no: int) -> Dict[str, Any]:
        """사용자 건물 데이터 캐싱"""
        try:
            buildings = self.db.query(models.Building).filter(
                models.Building.user_no == user_no
            ).all()
            
            buildings_data = {}
            for building in buildings:
                buildings_data[building.building_idx] = {
                    "id": building.id,
                    "user_no": building.user_no,
                    "building_idx": building.building_idx,
                    "building_lv": building.building_lv,
                    "status": building.status,
                    "start_time": building.start_time.isoformat() if building.start_time else None,
                    "end_time": building.end_time.isoformat() if building.end_time else None,
                    "last_dt": building.last_dt.isoformat() if building.last_dt else None
                }
            
            success = self.cache_manager.cache_user_data(user_no, 'buildings', buildings_data)
            return {"success": success, "count": len(buildings_data)}
            
        except Exception as e:
            print(f"Error caching buildings for user {user_no}: {e}")
            return {"success": False, "count": 0}
    
    def _cache_user_units(self, user_no: int) -> Dict[str, Any]:
        """사용자 유닛 데이터 캐싱"""
        try:
            # 보유 유닛
            user_units = self.db.query(models.UserUnit).filter(
                models.UserUnit.user_no == user_no
            ).all()
            
            units_data = {
                'inventory': {},
                'production_queue': {}
            }
            
            # 보유 유닛 데이터
            for unit in user_units:
                units_data['inventory'][unit.unit_idx] = {
                    "unit_idx": unit.unit_idx,
                    "quantity": unit.quantity,
                    "last_dt": unit.last_dt.isoformat() if unit.last_dt else None
                }
            
            # 생산 큐 데이터
            production_queue = self.db.query(models.UnitProductionQueue).filter(
                models.UnitProductionQueue.user_no == user_no
            ).all()
            
            for queue_item in production_queue:
                key = f"{queue_item.unit_idx}_{queue_item.queue_slot}"
                units_data['production_queue'][key] = {
                    "unit_idx": queue_item.unit_idx,
                    "queue_slot": queue_item.queue_slot,
                    "quantity": queue_item.quantity,
                    "status": queue_item.status,
                    "start_time": queue_item.start_time.isoformat() if queue_item.start_time else None,
                    "end_time": queue_item.end_time.isoformat() if queue_item.end_time else None
                }
            
            success = self.cache_manager.cache_user_data(user_no, 'units', units_data)
            total_count = len(units_data['inventory']) + len(units_data['production_queue'])
            return {"success": success, "count": total_count}
            
        except Exception as e:
            print(f"Error caching units for user {user_no}: {e}")
            return {"success": False, "count": 0}
    
    def _cache_user_research(self, user_no: int) -> Dict[str, Any]:
        """사용자 연구 데이터 캐싱"""
        try:
            research_data = self.db.query(models.UserResearch).filter(
                models.UserResearch.user_no == user_no
            ).all()
            
            research_dict = {}
            for research in research_data:
                research_dict[research.research_idx] = {
                    "research_idx": research.research_idx,
                    "status": research.status,  # 0: 미완료, 1: 진행중, 2: 완료
                    "start_time": research.start_time.isoformat() if research.start_time else None,
                    "end_time": research.end_time.isoformat() if research.end_time else None,
                    "completion_time": research.completion_time.isoformat() if research.completion_time else None
                }
            
            success = self.cache_manager.cache_user_data(user_no, 'research', research_dict)
            return {"success": success, "count": len(research_dict)}
            
        except Exception as e:
            print(f"Error caching research for user {user_no}: {e}")
            return {"success": False, "count": 0}
    
    def _cache_user_resources(self, user_no: int) -> Dict[str, Any]:
        """사용자 자원 데이터 캐싱"""
        try:
            resources = self.db.query(models.UserResource).filter(
                models.UserResource.user_no == user_no
            ).all()
            
            resource_data = {}
            for resource in resources:
                resource_data[resource.resource_type] = {
                    "resource_type": resource.resource_type,
                    "amount": resource.amount,
                    "last_updated": resource.last_dt.isoformat() if resource.last_dt else None
                }
            
            success = self.cache_manager.cache_user_data(user_no, 'resources', resource_data)
            return {"success": success, "count": len(resource_data)}
            
        except Exception as e:
            print(f"Error caching resources for user {user_no}: {e}")
            return {"success": False, "count": 0}
    
    def _cache_user_buffs(self, user_no: int) -> Dict[str, Any]:
        """사용자 버프 데이터 캐싱"""
        try:
            buffs = self.db.query(models.UserBuff).filter(
                models.UserBuff.user_no == user_no,
                models.UserBuff.is_active == True
            ).all()
            
            buff_data = {}
            for buff in buffs:
                buff_data[buff.id] = {
                    "buff_id": buff.id,
                    "buff_type": buff.buff_type,
                    "buff_value": buff.buff_value,
                    "start_time": buff.start_time.isoformat() if buff.start_time else None,
                    "end_time": buff.end_time.isoformat() if buff.end_time else None,
                    "is_active": buff.is_active
                }
            
            success = self.cache_manager.cache_user_data(user_no, 'buffs', buff_data)
            return {"success": success, "count": len(buff_data)}
            
        except Exception as e:
            print(f"Error caching buffs for user {user_no}: {e}")
            return {"success": False, "count": 0}
    
    def _sync_active_tasks_to_redis(self, user_no: int):
        """진행 중인 모든 작업들을 Redis 큐에 동기화"""
        try:
            # 건물 동기화
            self._sync_buildings_to_redis(user_no)
            
            # 유닛 생산 동기화
            self._sync_units_to_redis(user_no)
            
            # 연구 동기화
            self._sync_research_to_redis(user_no)
            
            # 버프 동기화
            self._sync_buffs_to_redis(user_no)
            
        except Exception as e:
            print(f"Error syncing active tasks to Redis for user {user_no}: {e}")
    
    def _sync_buildings_to_redis(self, user_no: int):
        """진행 중인 건물을 Redis에 동기화"""
        try:
            building_redis = self.redis_manager.get_building_manager()
            
            active_buildings = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.status.in_([1, 2]),
                models.Building.end_time.isnot(None)
            ).all()
            
            for building in active_buildings:
                existing_time = building_redis.get_building_completion_time(
                    user_no, building.building_idx
                )
                
                if not existing_time:
                    building_redis.add_building_to_queue(
                        user_no, building.building_idx, building.end_time
                    )
                    
        except Exception as e:
            print(f"Error syncing buildings to Redis: {e}")
    
    def _sync_units_to_redis(self, user_no: int):
        """진행 중인 유닛 생산을 Redis에 동기화"""
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            
            active_productions = self.db.query(models.UnitProductionQueue).filter(
                models.UnitProductionQueue.user_no == user_no,
                models.UnitProductionQueue.status == 1,
                models.UnitProductionQueue.end_time.isnot(None)
            ).all()
            
            for production in active_productions:
                existing_time = unit_redis.get_completion_time(
                    user_no, production.unit_idx, production.queue_slot
                )
                
                if not existing_time:
                    unit_redis.add_to_queue(
                        user_no, production.unit_idx, production.end_time, production.queue_slot
                    )
                    
        except Exception as e:
            print(f"Error syncing units to Redis: {e}")
    
    def _sync_research_to_redis(self, user_no: int):
        """진행 중인 연구를 Redis에 동기화"""
        try:
            research_redis = self.redis_manager.get_research_manager()
            
            active_research = self.db.query(models.UserResearch).filter(
                models.UserResearch.user_no == user_no,
                models.UserResearch.status == 1,
                models.UserResearch.end_time.isnot(None)
            ).all()
            
            for research in active_research:
                existing_time = research_redis.get_completion_time(
                    user_no, research.research_idx
                )
                
                if not existing_time:
                    research_redis.add_to_queue(
                        user_no, research.research_idx, research.end_time
                    )
                    
        except Exception as e:
            print(f"Error syncing research to Redis: {e}")
    
    def _sync_buffs_to_redis(self, user_no: int):
        """활성 버프를 Redis에 동기화"""
        try:
            buff_redis = self.redis_manager.get_buff_manager()
            
            active_buffs = self.db.query(models.UserBuff).filter(
                models.UserBuff.user_no == user_no,
                models.UserBuff.is_active == True,
                models.UserBuff.end_time.isnot(None)
            ).all()
            
            for buff in active_buffs:
                existing_time = buff_redis.get_completion_time(
                    user_no, buff.id
                )
                
                if not existing_time:
                    buff_redis.add_to_queue(
                        user_no, buff.id, buff.end_time
                    )
                    
        except Exception as e:
            print(f"Error syncing buffs to Redis: {e}")