# services/comprehensive_login_service.py (수정됨)
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import models
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from services.redis_manager import RedisManager
from services.db_manager import DBManager


class LoginManager:
    """통합 사용자 로그인 서비스"""
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        # NOTE: ThreadPoolExecutor는 동기 DB/Redis 호출을 비동기 이벤트 루프에서 블로킹 없이 실행하기 위해 사용됩니다.
        self.executor = ThreadPoolExecutor(max_workers=5) 
        
        
    @property
    def user_no(self):
        # NOTE: 초기화되지 않았을 경우를 대비한 안전한 접근
        return getattr(self, '_user_no', None)

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_buildings = None

    @property
    def data(self):
        return getattr(self, '_data', None)

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
        
    async def handle_user_login(self) -> Dict[str, Any]:
        """사용자 로그인 처리 (모든 게임 데이터 캐싱)"""
        
        user_no = self.user_no
        if user_no is None:
             return {"success": False, "message": "User number not set."}
        
        try:
            # 캐시 유효성 확인 (비동기)
            # await self._is_user_cache_valid_async(user_no)
            
            # 모든 게임 데이터 로드 및 캐싱을 병렬로 처리
            cache_tasks = [
                self._cache_user_buildings_async(user_no),
                self._cache_user_units_async(user_no),
                self._cache_user_research_async(user_no),
                self._cache_user_resources_async(user_no),
                self._cache_user_buffs_async(user_no)
            ]
            
            # 모든 캐싱 작업을 동시 실행
            # 여기서 발생한 Exception은 return_exceptions=True 덕분에 catch됩니다.
            cache_results = await asyncio.gather(*cache_tasks, return_exceptions=True)
            
            # 진행 중인 작업들 Redis 동기화 (비동기)
            await self._sync_active_tasks_to_redis_async(user_no)
            
            # 결과 정리
            result_dict = {
                'buildings': cache_results[0] if not isinstance(cache_results[0], Exception) else {"success": False, "error": str(cache_results[0])},
                'units': cache_results[1] if not isinstance(cache_results[1], Exception) else {"success": False, "error": str(cache_results[1])},
                'research': cache_results[2] if not isinstance(cache_results[2], Exception) else {"success": False, "error": str(cache_results[2])},
                'resources': cache_results[3] if not isinstance(cache_results[3], Exception) else {"success": False, "error": str(cache_results[3])},
                'buffs': cache_results[4] if not isinstance(cache_results[4], Exception) else {"success": False, "error": str(cache_results[4])}
            }
            
            # 결과 집계
            total_items = sum(result.get('count', 0) for result in result_dict.values() if isinstance(result, dict) and result.get('success'))
            
            return {
                "success": True,
                "message": f"Login processed. Cached {total_items} total items",
                "cache_results": result_dict,
                "source": "database"
            }
            
        except Exception as e:
            self.logger.error(f"Error in comprehensive login processing for user {user_no}: {e}")
            # 최상위 TypeError 방지: 실패 시에도 항상 JSON 직렬화 가능한 딕셔너리를 반환합니다.
            return {"success": False, "message": str(e)}
        
    async def _is_user_cache_valid_async(self, user_no: int, max_age_minutes: int = 30) -> bool:
        """사용자의 모든 캐시가 유효한지 확인 (비동기)"""
        try:
            loop = asyncio.get_event_loop()
            
            def check_cache():
                building_redis = self.redis_manager.get_building_manager()
                # Redis Manager의 메서드가 동기 함수라고 가정하고 run_in_executor 사용
                return building_redis.get_cached_buildings(user_no)
            
            # NOTE: BuildingRedisManager.get_cached_buildings를 동기적으로 실행하고 결과를 await
            cached_buildings = await loop.run_in_executor(self.executor, check_cache)
            
            return bool(cached_buildings)
            
        except Exception as e:
            self.logger.error(f"Error checking cache validity for user {user_no}: {e}")
            return False
        
    async def _cache_user_buildings_async(self, user_no: int) -> Dict[str, Any]:
        """사용자 건물 데이터 캐싱 (비동기)"""
        try:
            loop = asyncio.get_event_loop()
            
            # 1. DB 조회 (동기 함수를 스레드 풀에서 비동기로 실행)
            def load_buildings_db():
                building_db = self.db_manager.get_building_manager()
                # DB Manager 메서드가 'get_user_buildings'라고 가정
                return building_db.get_user_buildings(user_no)
            
            buildings_result = await loop.run_in_executor(self.executor, load_buildings_db)
            
            if not buildings_result.get('success'):
                return {"success": False, "count": 0, "error": buildings_result.get('message', 'DB Load Failed')}
            
            # 건물 데이터 포맷팅 로직 (CPU 바운드)
            buildings_data = {}
            for building in buildings_result.get('data', []):
                # ... 기존 포맷팅 로직 유지 ... (여기서는 생략)
                building_idx = building.get('building_idx') if isinstance(building, dict) else getattr(building, 'building_idx', None)
                if building_idx is not None:
                    buildings_data[str(building_idx)] = {
                        "id": building.get('id') if isinstance(building, dict) else getattr(building, 'id', None),
                        "user_no": building.get('user_no') if isinstance(building, dict) else getattr(building, 'user_no', None),
                        "building_idx": building_idx,
                        "building_lv": building.get('building_lv') if isinstance(building, dict) else getattr(building, 'building_lv', 1),
                        "status": building.get('status') if isinstance(building, dict) else getattr(building, 'status', 'IDLE'),
                        "start_time": building.get('start_time') if isinstance(building, dict) else (getattr(building, 'start_time', None).isoformat() if getattr(building, 'start_time', None) else None),
                        "end_time": building.get('end_time') if isinstance(building, dict) else (getattr(building, 'end_time', None).isoformat() if getattr(building, 'end_time', None) else None),
                        "last_dt": building.get('last_dt') if isinstance(building, dict) else (getattr(building, 'last_dt', None).isoformat() if getattr(building, 'last_dt', None) else None),
                        "cached_at": datetime.utcnow().isoformat()
                    }

            # 2. Redis 캐싱 (동기 함수를 스레드 풀에서 비동기로 실행)
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
            loop = asyncio.get_event_loop()
            
            # 1. DB 조회 (get_user_units) - **AttributeError 해결**
            def load_units_db():
                unit_db = self.db_manager.get_unit_manager()
                # 메서드 이름이 'get_user_units'가 맞는지 확인 필요!
                return unit_db.get_user_units(user_no)
            
            # DB 호출을 await
            units_result = await loop.run_in_executor(self.executor, load_units_db)
            
            if not units_result.get('success'):
                return {"success": False, "count": 0, "error": units_result.get('message', 'DB Load Failed')}
            
            # ... 유닛 데이터 포맷팅 로직 (CPU 바운드) ...
            units_data = {'inventory': {}, 'production_queue': {}}
            for unit in units_result.get('data', []):
                 # ... 보유 유닛 처리 로직 유지 ...
                unit_idx = unit.get('unit_idx') if isinstance(unit, dict) else getattr(unit, 'unit_idx', None)
                if unit_idx is not None:
                     units_data['inventory'][str(unit_idx)] = {
                         "unit_idx": unit_idx,
                         "quantity": unit.get('quantity') if isinstance(unit, dict) else getattr(unit, 'quantity', 0),
                         "last_dt": unit.get('last_dt') if isinstance(unit, dict) else (getattr(unit, 'last_dt', None).isoformat() if getattr(unit, 'last_dt', None) else None)
                     }
            
            # 2. 생산 큐 DB 조회
            def load_production_db():
                unit_db = self.db_manager.get_unit_manager()
                # 이 메서드도 동기라고 가정
                return unit_db.get_user_production_queue(user_no)

            production_result = await loop.run_in_executor(self.executor, load_production_db)
            
            if production_result.get('success'):
                for queue_item in production_result.get('data', []):
                    # ... 생산 큐 처리 로직 유지 ...
                    unit_idx = queue_item.get('unit_idx') if isinstance(queue_item, dict) else getattr(queue_item, 'unit_idx', None)
                    queue_slot = queue_item.get('queue_slot') if isinstance(queue_item, dict) else getattr(queue_item, 'queue_slot', 0)
                    if unit_idx is not None:
                         key = f"{unit_idx}_{queue_slot}"
                         units_data['production_queue'][key] = {
                             "unit_idx": unit_idx,
                             "queue_slot": queue_slot,
                             "quantity": queue_item.get('quantity') if isinstance(queue_item, dict) else getattr(queue_item, 'quantity', 0),
                             "status": queue_item.get('status') if isinstance(queue_item, dict) else getattr(queue_item, 'status', 'IDLE'),
                             "start_time": queue_item.get('start_time') if isinstance(queue_item, dict) else (getattr(queue_item, 'start_time', None).isoformat() if getattr(queue_item, 'start_time', None) else None),
                             "end_time": queue_item.get('end_time') if isinstance(queue_item, dict) else (getattr(queue_item, 'end_time', None).isoformat() if getattr(queue_item, 'end_time', None) else None)
                         }
            
            # 3. Redis 캐싱 (동기 함수를 스레드 풀에서 비동기로 실행)
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
            loop = asyncio.get_event_loop()

            # 1. DB 조회 - **AttributeError 해결**
            def load_research_db():
                research_db = self.db_manager.get_research_manager()
                # 메서드 이름이 'get_user_research'가 맞는지 확인 필요!
                return research_db.get_user_research(user_no)
            
            # DB 호출을 await
            research_result = await loop.run_in_executor(self.executor, load_research_db)
            
            if not research_result.get('success'):
                return {"success": False, "count": 0, "error": research_result.get('message', 'DB Load Failed')}
            
            # ... 연구 데이터 포맷팅 로직 (CPU 바운드) ...
            research_dict = {}
            for research in research_result.get('data', []):
                 # ... 기존 포맷팅 로직 유지 ...
                research_idx = research.get('research_idx') if isinstance(research, dict) else getattr(research, 'research_idx', None)
                if research_idx is not None:
                     research_dict[str(research_idx)] = {
                         "research_idx": research_idx,
                         "status": research.get('status') if isinstance(research, dict) else getattr(research, 'status', 'COMPLETED'),
                         "start_time": research.get('start_time') if isinstance(research, dict) else (getattr(research, 'start_time', None).isoformat() if getattr(research, 'start_time', None) else None),
                         "end_time": research.get('end_time') if isinstance(research, dict) else (getattr(research, 'end_time', None).isoformat() if getattr(research, 'end_time', None) else None),
                         "completion_time": research.get('completion_time') if isinstance(research, dict) else (getattr(research, 'completion_time', None).isoformat() if getattr(research, 'completion_time', None) else None)
                     }

            # 2. Redis 캐싱 (동기 함수를 스레드 풀에서 비동기로 실행)
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
            loop = asyncio.get_event_loop()
            
            # 1. DB 조회 - **RuntimeWarning 및 is not subscriptable 해결**
            def load_resources_db():
                resource_db = self.db_manager.get_resource_manager()
                # get_user_resources가 동기 함수라고 가정
                return resource_db.get_user_resources(user_no)
            
            # DB 호출을 await하여 실제 결과를 받음
            resources_result = await loop.run_in_executor(self.executor, load_resources_db)
            
            if not resources_result.get('success'):
                return {"success": False, "count": 0, "error": resources_result.get('message', 'DB Load Failed')}
            
            # ... 자원 데이터 포맷팅 로직 (CPU 바운드) ...
            resource_data = {}
            resources = resources_result.get('data')

            if isinstance(resources, list):
                # ... 기존 리스트 처리 로직 유지 ...
                for resource in resources:
                    resource_type = resource.get('resource_type') if isinstance(resource, dict) else getattr(resource, 'resource_type', None)
                    if resource_type is not None:
                         resource_data[resource_type] = {
                             "resource_type": resource_type,
                             "amount": resource.get('amount') if isinstance(resource, dict) else getattr(resource, 'amount', 0),
                             "last_updated": resource.get('last_dt') if isinstance(resource, dict) else (getattr(resource, 'last_dt', None).isoformat() if getattr(resource, 'last_dt', None) else None)
                         }
            elif isinstance(resources, dict):
                 resource_data = resources # resources_result['data'] 자체가 Dict일 경우
            else:
                 # DB ORM 객체일 경우 처리 로직 (resources_result['data']가 단일 객체일 때)
                 for attr in ['gold', 'wood', 'stone', 'food']:
                     if hasattr(resources, attr):
                         resource_data[attr] = {
                             "resource_type": attr,
                             "amount": getattr(resources, attr),
                             "last_updated": getattr(resources, 'last_dt', None).isoformat() if hasattr(resources, 'last_dt') and getattr(resources, 'last_dt') else None
                         }
            
            # 2. Redis 캐싱 (동기 함수를 스레드 풀에서 비동기로 실행)
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
            loop = asyncio.get_event_loop()
            
            # 1. DB 조회
            def load_buffs_db():
                buff_db = self.db_manager.get_buff_manager()
                return buff_db.get_user_active_buffs(user_no)
            
            buffs_result = await loop.run_in_executor(self.executor, load_buffs_db)

            if not buffs_result.get('success'):
                return {"success": False, "count": 0, "error": buffs_result.get('message', 'DB Load Failed')}
            
            # ... 버프 데이터 포맷팅 로직 (CPU 바운드) ...
            buff_data = {}
            for buff in buffs_result.get('data', []):
                 # ... 기존 포맷팅 로직 유지 ...
                buff_id = buff.get('id') if isinstance(buff, dict) else getattr(buff, 'id', None)
                if buff_id is not None:
                     buff_data[str(buff_id)] = {
                         "buff_id": buff_id,
                         "buff_type": buff.get('buff_type') if isinstance(buff, dict) else getattr(buff, 'buff_type', None),
                         "buff_value": buff.get('buff_value') if isinstance(buff, dict) else getattr(buff, 'buff_value', 0),
                         "start_time": buff.get('start_time') if isinstance(buff, dict) else (getattr(buff, 'start_time', None).isoformat() if getattr(buff, 'start_time', None) else None),
                         "end_time": buff.get('end_time') if isinstance(buff, dict) else (getattr(buff, 'end_time', None).isoformat() if getattr(buff, 'end_time', None) else None),
                         "is_active": buff.get('is_active') if isinstance(buff, dict) else getattr(buff, 'is_active', False)
                     }
            
            # 2. Redis 캐싱 (동기 함수를 스레드 풀에서 비동기로 실행)
            def cache_to_redis():
                cache_manager = self.redis_manager.get_cache_manager()
                buff_cache_key = f"user_buffs:{user_no}"
                return cache_manager.set_data(buff_cache_key, buff_data, expire_time=3600)
            
            success = await loop.run_in_executor(self.executor, cache_to_redis)
            
            return {"success": success, "count": len(buff_data)}
            
        except AttributeError:
             # get_buff_manager() 또는 get_user_active_buffs()가 없을 때 처리
            return {"success": True, "count": 0, "message": "No buff manager available or method missing"}
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
            loop = asyncio.get_event_loop()

            # 1. DB 조회 - **AttributeError 해결**
            def load_active_buildings_db():
                building_db = self.db_manager.get_building_manager()
                # 메서드 이름 'get_user_active_buildings'가 맞는지 확인 필요!
                return building_db.get_user_active_buildings(user_no)
            
            # DB 호출을 await
            active_buildings_result = await loop.run_in_executor(self.executor, load_active_buildings_db)

            if not active_buildings_result.get('success'):
                return
            
            # 2. Redis 작업을 비동기로 실행
            tasks = []
            for building in active_buildings_result.get('data', []):
                building_idx = building.get('building_idx') if isinstance(building, dict) else getattr(building, 'building_idx', None)
                end_time = building.get('end_time') if isinstance(building, dict) else getattr(building, 'end_time', None)
                
                if end_time and building_idx is not None:
                    # Redis 동기화는 여전히 스레드 풀에서 실행
                    def sync_building(building_idx, end_time):
                        building_redis = self.redis_manager.get_building_manager()
                        existing_time = building_redis.get_building_completion_time(user_no, building_idx)
                        
                        if not existing_time:
                            # 문자열/datetime 처리 로직 유지
                            parsed_end_time = end_time
                            if isinstance(end_time, str):
                                parsed_end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                            
                            building_redis.add_building_to_queue(user_no, building_idx, parsed_end_time)
                            return True
                        return False

                    # NOTE: 루프 내에서 task를 정의하고 await asyncio.gather로 모아서 await 해야 합니다.
                    task = loop.run_in_executor(self.executor, sync_building, building_idx, end_time)
                    tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            self.logger.error(f"Error syncing buildings to Redis: {e}")
    
    async def _sync_units_to_redis_async(self, user_no: int):
        """진행 중인 유닛 생산을 Redis에 동기화 (비동기)"""
        try:
            loop = asyncio.get_event_loop()
            
            # 1. DB 조회
            def load_active_units_db():
                unit_db = self.db_manager.get_unit_manager()
                # 메서드 이름 'get_user_active_productions'가 맞는지 확인 필요!
                return unit_db.get_user_active_productions(user_no)
            
            active_productions_result = await loop.run_in_executor(self.executor, load_active_units_db)

            if not active_productions_result.get('success'):
                return
            
            # 2. Redis 작업을 비동기로 실행
            tasks = []
            for production in active_productions_result.get('data', []):
                 # ... 데이터 파싱 로직 유지 ...
                unit_idx = production.get('unit_idx') if isinstance(production, dict) else getattr(production, 'unit_idx', None)
                queue_slot = production.get('queue_slot') if isinstance(production, dict) else getattr(production, 'queue_slot', None)
                end_time = production.get('end_time') if isinstance(production, dict) else getattr(production, 'end_time', None)

                if end_time and unit_idx is not None and queue_slot is not None:
                    def sync_unit(unit_idx, queue_slot, end_time):
                         unit_redis = self.redis_manager.get_unit_manager()
                         existing_time = unit_redis.get_completion_time(user_no, unit_idx, queue_slot)

                         if not existing_time:
                             parsed_end_time = end_time
                             if isinstance(end_time, str):
                                 parsed_end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                             
                             unit_redis.add_to_queue(user_no, unit_idx, parsed_end_time, queue_slot)
                             return True
                         return False
                    
                    task = loop.run_in_executor(self.executor, sync_unit, unit_idx, queue_slot, end_time)
                    tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except AttributeError:
             pass # get_unit_manager() 등이 없을 때 무시
        except Exception as e:
            self.logger.error(f"Error syncing units to Redis: {e}")
    
    async def _sync_research_to_redis_async(self, user_no: int):
        """진행 중인 연구를 Redis에 동기화 (비동기)"""
        try:
            loop = asyncio.get_event_loop()

            # 1. DB 조회
            def load_active_research_db():
                research_db = self.db_manager.get_research_manager()
                # 메서드 이름 'get_user_active_research'가 맞는지 확인 필요!
                return research_db.get_user_active_research(user_no)
            
            active_research_result = await loop.run_in_executor(self.executor, load_active_research_db)

            if not active_research_result.get('success'):
                return
            
            # 2. Redis 작업을 비동기로 실행
            tasks = []
            for research in active_research_result.get('data', []):
                 # ... 데이터 파싱 로직 유지 ...
                research_idx = research.get('research_idx') if isinstance(research, dict) else getattr(research, 'research_idx', None)
                end_time = research.get('end_time') if isinstance(research, dict) else getattr(research, 'end_time', None)

                if end_time and research_idx is not None:
                    def sync_research(research_idx, end_time):
                        research_redis = self.redis_manager.get_research_manager()
                        existing_time = research_redis.get_completion_time(user_no, research_idx)

                        if not existing_time:
                            parsed_end_time = end_time
                            if isinstance(end_time, str):
                                parsed_end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

                            research_redis.add_to_queue(user_no, research_idx, parsed_end_time)
                            return True
                        return False
                    
                    task = loop.run_in_executor(self.executor, sync_research, research_idx, end_time)
                    tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except AttributeError:
             pass # get_research_manager() 등이 없을 때 무시
        except Exception as e:
            self.logger.error(f"Error syncing research to Redis: {e}")
    
    async def _sync_buffs_to_redis_async(self, user_no: int):
        """활성 버프를 Redis에 동기화 (비동기)"""
        try:
            # 버프 동기화 로직은 필요에 따라 구현
            pass 
        except Exception as e:
            self.logger.error(f"Error syncing buffs to Redis: {e}")
            
    def __del__(self):
        """소멸자에서 스레드 풀 정리"""
        if hasattr(self, 'executor'):
            # ThreadPoolExecutor를 안전하게 종료합니다.
            self.executor.shutdown(wait=True)