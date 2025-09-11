# services/comprehensive_login_service.py
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import models
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

from services.redis_manager import RedisManager
from services.db_manager import DBManager


class LoginManager:
    """통합 사용자 로그인 서비스"""
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.executor = ThreadPoolExecutor(max_workers=5)  # Redis 작업용 스레드 풀
        
        
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_buildings = None

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
        
    async def handle_user_login(self) -> Dict[str, Any]:
        """사용자 로그인 처리 (모든 게임 데이터 캐싱)"""
        
        user_no = self.user_no
        try:
            # 캐시 유효성 확인 (비동기)
            cache_valid = await self._is_user_cache_valid_async(user_no)
            if cache_valid:
                return {"success": True, "message": "Using cached data", "source": "cache"}
            
            # 모든 게임 데이터 로드 및 캐싱을 병렬로 처리
            cache_tasks = [
                self._cache_user_buildings_async(user_no),
                self._cache_user_units_async(user_no),
                self._cache_user_research_async(user_no),
                self._cache_user_resources_async(user_no),
                self._cache_user_buffs_async(user_no)
            ]
            
            # 모든 캐싱 작업을 동시 실행
            cache_results = await asyncio.gather(*cache_tasks, return_exceptions=True)
            
            # 결과 정리
            result_dict = {
                'buildings': cache_results[0] if not isinstance(cache_results[0], Exception) else {"success": False, "error": str(cache_results[0])},
                'units': cache_results[1] if not isinstance(cache_results[1], Exception) else {"success": False, "error": str(cache_results[1])},
                'research': cache_results[2] if not isinstance(cache_results[2], Exception) else {"success": False, "error": str(cache_results[2])},
                'resources': cache_results[3] if not isinstance(cache_results[3], Exception) else {"success": False, "error": str(cache_results[3])},
                'buffs': cache_results[4] if not isinstance(cache_results[4], Exception) else {"success": False, "error": str(cache_results[4])}
            }
            
            # 진행 중인 작업들 Redis 동기화 (비동기)
            await self._sync_active_tasks_to_redis_async(user_no)
            
            # 결과 집계
            total_items = sum(result.get('count', 0) for result in result_dict.values() if isinstance(result, dict))
            
            return {
                "success": True,
                "message": f"Login processed. Cached {total_items} total items",
                "cache_results": result_dict,
                "source": "database"
            }
            
        except Exception as e:
            self.logger.error(f"Error in comprehensive login processing for user {user_no}: {e}")
            return {"success": False, "message": str(e)}
    
    async def _is_user_cache_valid_async(self, user_no: int, max_age_minutes: int = 30) -> bool:
        """사용자의 모든 캐시가 유효한지 확인 (비동기)"""
        try:
            # Redis 작업을 스레드 풀에서 실행
            loop = asyncio.get_event_loop()
            
            def check_cache():
                building_redis = self.redis_manager.get_building_manager()
                return building_redis.get_cached_buildings(user_no)
            
            cached_buildings = await loop.run_in_executor(self.executor, check_cache)
            
            if not cached_buildings:
                return False
            
            # 추가적인 캐시 유효성 검사는 필요에 따라 구현
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking cache validity for user {user_no}: {e}")
            return False
    
    async def _cache_user_buildings_async(self, user_no: int) -> Dict[str, Any]:
        """사용자 건물 데이터 캐싱 (비동기)"""
        try:
            # DB 조회는 동기로 실행
            building_db = self.db_manager.get_building_manager()
            buildings_result = building_db.get_user_buildings(user_no)
            
            if not buildings_result['success']:
                return {"success": False, "count": 0, "error": buildings_result.get('message')}
            
            # 건물 데이터 포맷팅
            buildings_data = {}
            for building in buildings_result['data']:
                building_idx = building.get('building_idx') if isinstance(building, dict) else building.building_idx
                buildings_data[str(building_idx)] = {
                    "id": building.get('id') if isinstance(building, dict) else building.id,
                    "user_no": building.get('user_no') if isinstance(building, dict) else building.user_no,
                    "building_idx": building_idx,
                    "building_lv": building.get('building_lv') if isinstance(building, dict) else building.building_lv,
                    "status": building.get('status') if isinstance(building, dict) else building.status,
                    "start_time": building.get('start_time') if isinstance(building, dict) else (building.start_time.isoformat() if building.start_time else None),
                    "end_time": building.get('end_time') if isinstance(building, dict) else (building.end_time.isoformat() if building.end_time else None),
                    "last_dt": building.get('last_dt') if isinstance(building, dict) else (building.last_dt.isoformat() if building.last_dt else None),
                    "cached_at": "datetime.utcnow().isoformat()"
                }
            
            # Redis 캐싱을 비동기로 실행
            loop = asyncio.get_event_loop()
            
            def cache_to_redis():
                building_redis = self.redis_manager.get_building_manager()
                return building_redis.cache_user_buildings_data(user_no, buildings_data)
            
            success = await loop.run_in_executor(self.executor, cache_to_redis)
            
            return {"success": success, "count": len(buildings_data)}
            
        except Exception as e:
            self.logger.error(f"Error caching buildings for user {user_no}: {e}")
            return {"success": False, "count": 0, "error": str(e)}
    
    async def _cache_user_units_async(self, user_no: int) -> Dict[str, Any]:
        """사용자 유닛 데이터 캐싱 (비동기)"""
        try:
            # DB 조회
            unit_db = self.db_manager.get_unit_manager()
            units_result = unit_db.get_user_units(user_no)
            
            if not units_result['success']:
                return {"success": False, "count": 0, "error": units_result.get('message')}
            
            units_data = {
                'inventory': {},
                'production_queue': {}
            }
            
            # 보유 유닛 데이터 처리
            for unit in units_result['data']:
                unit_idx = unit.get('unit_idx') if isinstance(unit, dict) else unit.unit_idx
                units_data['inventory'][str(unit_idx)] = {
                    "unit_idx": unit_idx,
                    "quantity": unit.get('quantity') if isinstance(unit, dict) else unit.quantity,
                    "last_dt": unit.get('last_dt') if isinstance(unit, dict) else (unit.last_dt.isoformat() if unit.last_dt else None)
                }
            
            # 생산 큐 데이터 조회
            try:
                production_result = unit_db.get_user_production_queue(user_no)
                if production_result['success']:
                    for queue_item in production_result['data']:
                        unit_idx = queue_item.get('unit_idx') if isinstance(queue_item, dict) else queue_item.unit_idx
                        queue_slot = queue_item.get('queue_slot') if isinstance(queue_item, dict) else queue_item.queue_slot
                        key = f"{unit_idx}_{queue_slot}"
                        
                        units_data['production_queue'][key] = {
                            "unit_idx": unit_idx,
                            "queue_slot": queue_slot,
                            "quantity": queue_item.get('quantity') if isinstance(queue_item, dict) else queue_item.quantity,
                            "status": queue_item.get('status') if isinstance(queue_item, dict) else queue_item.status,
                            "start_time": queue_item.get('start_time') if isinstance(queue_item, dict) else (queue_item.start_time.isoformat() if queue_item.start_time else None),
                            "end_time": queue_item.get('end_time') if isinstance(queue_item, dict) else (queue_item.end_time.isoformat() if queue_item.end_time else None)
                        }
            except AttributeError:
                pass
            
            # Redis 캐싱을 비동기로 실행
            loop = asyncio.get_event_loop()
            
            def cache_to_redis():
                unit_redis = self.redis_manager.get_unit_manager()
                return unit_redis.cache_user_units_data(user_no, units_data)
            
            success = await loop.run_in_executor(self.executor, cache_to_redis)
            
            total_count = len(units_data['inventory']) + len(units_data['production_queue'])
            return {"success": success, "count": total_count}
            
        except Exception as e:
            self.logger.error(f"Error caching units for user {user_no}: {e}")
            return {"success": False, "count": 0, "error": str(e)}
    
    async def _cache_user_research_async(self, user_no: int) -> Dict[str, Any]:
        """사용자 연구 데이터 캐싱 (비동기)"""
        try:
            # DB 조회
            research_db = self.db_manager.get_research_manager()
            research_result = research_db.get_user_research(user_no)
            
            if not research_result['success']:
                return {"success": False, "count": 0, "error": research_result.get('message')}
            
            research_dict = {}
            for research in research_result['data']:
                research_idx = research.get('research_idx') if isinstance(research, dict) else research.research_idx
                research_dict[str(research_idx)] = {
                    "research_idx": research_idx,
                    "status": research.get('status') if isinstance(research, dict) else research.status,
                    "start_time": research.get('start_time') if isinstance(research, dict) else (research.start_time.isoformat() if research.start_time else None),
                    "end_time": research.get('end_time') if isinstance(research, dict) else (research.end_time.isoformat() if research.end_time else None),
                    "completion_time": research.get('completion_time') if isinstance(research, dict) else (research.completion_time.isoformat() if research.completion_time else None)
                }
            
            # Redis 캐싱을 비동기로 실행
            loop = asyncio.get_event_loop()
            
            def cache_to_redis():
                research_redis = self.redis_manager.get_research_manager()
                return research_redis.cache_user_research_data(user_no, research_dict)
            
            success = await loop.run_in_executor(self.executor, cache_to_redis)
            
            return {"success": success, "count": len(research_dict)}
            
        except Exception as e:
            self.logger.error(f"Error caching research for user {user_no}: {e}")
            return {"success": False, "count": 0, "error": str(e)}
    
    async def _cache_user_resources_async(self, user_no: int) -> Dict[str, Any]:
        """사용자 자원 데이터 캐싱 (비동기)"""
        try:
            # DB 조회
            resource_db = self.db_manager.get_resource_manager()
            resources_result = resource_db.get_user_resources(user_no)
            
            if not resources_result['success']:
                return {"success": False, "count": 0, "error": resources_result.get('message')}
            
            resource_data = {}
            resources = resources_result['data']
            
            # 자원 데이터 처리
            if isinstance(resources, list):
                for resource in resources:
                    resource_type = resource.get('resource_type') if isinstance(resource, dict) else resource.resource_type
                    resource_data[resource_type] = {
                        "resource_type": resource_type,
                        "amount": resource.get('amount') if isinstance(resource, dict) else resource.amount,
                        "last_updated": resource.get('last_dt') if isinstance(resource, dict) else (resource.last_dt.isoformat() if resource.last_dt else None)
                    }
            else:
                if isinstance(resources, dict):
                    resource_data = resources
                else:
                    for attr in ['gold', 'wood', 'stone', 'food']:
                        if hasattr(resources, attr):
                            resource_data[attr] = {
                                "resource_type": attr,
                                "amount": getattr(resources, attr),
                                "last_updated": resources.last_dt.isoformat() if hasattr(resources, 'last_dt') and resources.last_dt else None
                            }
            
            # Redis 캐싱을 비동기로 실행
            loop = asyncio.get_event_loop()
            
            def cache_to_redis():
                cache_manager = self.redis_manager.get_cache_manager()
                resource_cache_key = f"user_resources:{user_no}"
                return cache_manager.set_data(resource_cache_key, resource_data, expire_time=1800)
            
            success = await loop.run_in_executor(self.executor, cache_to_redis)
            
            return {"success": success, "count": len(resource_data)}
            
        except Exception as e:
            self.logger.error(f"Error caching resources for user {user_no}: {e}")
            return {"success": False, "count": 0, "error": str(e)}
    
    async def _cache_user_buffs_async(self, user_no: int) -> Dict[str, Any]:
        """사용자 버프 데이터 캐싱 (비동기)"""
        try:
            try:
                # DB 조회
                buff_db = self.db_manager.get_buff_manager()
                buffs_result = buff_db.get_user_active_buffs(user_no)
                
                if not buffs_result['success']:
                    return {"success": False, "count": 0, "error": buffs_result.get('message')}
                
                buff_data = {}
                for buff in buffs_result['data']:
                    buff_id = buff.get('id') if isinstance(buff, dict) else buff.id
                    buff_data[str(buff_id)] = {
                        "buff_id": buff_id,
                        "buff_type": buff.get('buff_type') if isinstance(buff, dict) else buff.buff_type,
                        "buff_value": buff.get('buff_value') if isinstance(buff, dict) else buff.buff_value,
                        "start_time": buff.get('start_time') if isinstance(buff, dict) else (buff.start_time.isoformat() if buff.start_time else None),
                        "end_time": buff.get('end_time') if isinstance(buff, dict) else (buff.end_time.isoformat() if buff.end_time else None),
                        "is_active": buff.get('is_active') if isinstance(buff, dict) else buff.is_active
                    }
                
                # Redis 캐싱을 비동기로 실행
                loop = asyncio.get_event_loop()
                
                def cache_to_redis():
                    cache_manager = self.redis_manager.get_cache_manager()
                    buff_cache_key = f"user_buffs:{user_no}"
                    return cache_manager.set_data(buff_cache_key, buff_data, expire_time=3600)
                
                success = await loop.run_in_executor(self.executor, cache_to_redis)
                
                return {"success": success, "count": len(buff_data)}
                
            except AttributeError:
                return {"success": True, "count": 0, "message": "No buff manager available"}
            
        except Exception as e:
            self.logger.error(f"Error caching buffs for user {user_no}: {e}")
            return {"success": False, "count": 0, "error": str(e)}
    
    async def _sync_active_tasks_to_redis_async(self, user_no: int):
        """진행 중인 모든 작업들을 Redis 큐에 동기화 (비동기)"""
        try:
            # 모든 동기화 작업을 병렬로 실행
            sync_tasks = [
                self._sync_buildings_to_redis_async(user_no),
                self._sync_units_to_redis_async(user_no),
                self._sync_research_to_redis_async(user_no),
                self._sync_buffs_to_redis_async(user_no)
            ]
            
            await asyncio.gather(*sync_tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"Error syncing active tasks to Redis for user {user_no}: {e}")
    
    async def _sync_buildings_to_redis_async(self, user_no: int):
        """진행 중인 건물을 Redis에 동기화 (비동기)"""
        try:
            # DB 조회
            building_db = self.db_manager.get_building_manager()
            active_buildings_result = building_db.get_user_active_buildings(user_no)
            
            if not active_buildings_result['success']:
                return
            
            # Redis 작업을 비동기로 실행
            loop = asyncio.get_event_loop()
            
            async def sync_building_tasks():
                tasks = []
                for building in active_buildings_result['data']:
                    building_idx = building.get('building_idx') if isinstance(building, dict) else building.building_idx
                    end_time = building.get('end_time') if isinstance(building, dict) else building.end_time
                    
                    if end_time:
                        def sync_building():
                            building_redis = self.redis_manager.get_building_manager()
                            existing_time = building_redis.get_building_completion_time(user_no, building_idx)
                            
                            if not existing_time:
                                if isinstance(end_time, str):
                                    from datetime import datetime
                                    parsed_end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                                else:
                                    parsed_end_time = end_time
                                
                                building_redis.add_building_to_queue(user_no, building_idx, parsed_end_time)
                        
                        task = loop.run_in_executor(self.executor, sync_building)
                        tasks.append(task)
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            
            await sync_building_tasks()
                            
        except Exception as e:
            self.logger.error(f"Error syncing buildings to Redis: {e}")
    
    async def _sync_units_to_redis_async(self, user_no: int):
        """진행 중인 유닛 생산을 Redis에 동기화 (비동기)"""
        try:
            unit_db = self.db_manager.get_unit_manager()
            
            try:
                active_productions_result = unit_db.get_user_active_productions(user_no)
                
                if not active_productions_result['success']:
                    return
                
                # Redis 작업을 비동기로 실행
                loop = asyncio.get_event_loop()
                
                async def sync_unit_tasks():
                    tasks = []
                    for production in active_productions_result['data']:
                        unit_idx = production.get('unit_idx') if isinstance(production, dict) else production.unit_idx
                        queue_slot = production.get('queue_slot') if isinstance(production, dict) else production.queue_slot
                        end_time = production.get('end_time') if isinstance(production, dict) else production.end_time
                        
                        if end_time:
                            def sync_unit():
                                unit_redis = self.redis_manager.get_unit_manager()
                                existing_time = unit_redis.get_completion_time(user_no, unit_idx, queue_slot)
                                
                                if not existing_time:
                                    if isinstance(end_time, str):
                                        from datetime import datetime
                                        parsed_end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                                    else:
                                        parsed_end_time = end_time
                                    
                                    unit_redis.add_to_queue(user_no, unit_idx, parsed_end_time, queue_slot)
                            
                            task = loop.run_in_executor(self.executor, sync_unit)
                            tasks.append(task)
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                
                await sync_unit_tasks()
                                
            except AttributeError:
                pass
                
        except Exception as e:
            self.logger.error(f"Error syncing units to Redis: {e}")
    
    async def _sync_research_to_redis_async(self, user_no: int):
        """진행 중인 연구를 Redis에 동기화 (비동기)"""
        try:
            research_db = self.db_manager.get_research_manager()
            
            try:
                active_research_result = research_db.get_user_active_research(user_no)
                
                if not active_research_result['success']:
                    return
                
                # Redis 작업을 비동기로 실행
                loop = asyncio.get_event_loop()
                
                async def sync_research_tasks():
                    tasks = []
                    for research in active_research_result['data']:
                        research_idx = research.get('research_idx') if isinstance(research, dict) else research.research_idx
                        end_time = research.get('end_time') if isinstance(research, dict) else research.end_time
                        
                        if end_time:
                            def sync_research():
                                research_redis = self.redis_manager.get_research_manager()
                                existing_time = research_redis.get_completion_time(user_no, research_idx)
                                
                                if not existing_time:
                                    if isinstance(end_time, str):
                                        from datetime import datetime
                                        parsed_end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                                    else:
                                        parsed_end_time = end_time
                                    
                                    research_redis.add_to_queue(user_no, research_idx, parsed_end_time)
                            
                            task = loop.run_in_executor(self.executor, sync_research)
                            tasks.append(task)
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                
                await sync_research_tasks()
                                
            except AttributeError:
                pass
                
        except Exception as e:
            self.logger.error(f"Error syncing research to Redis: {e}")
    
    async def _sync_buffs_to_redis_async(self, user_no: int):
        """활성 버프를 Redis에 동기화 (비동기)"""
        try:
            # 버프 동기화는 필요에 따라 구현
            pass
                
        except Exception as e:
            self.logger.error(f"Error syncing buffs to Redis: {e}")
            
    def __del__(self):
        """소멸자에서 스레드 풀 정리"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)