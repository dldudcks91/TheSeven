# services/comprehensive_login_service.py
from typing import Dict, Any
import logging
import asyncio
from datetime import datetime

from services.redis_manager import RedisManager
from services.db_manager import DBManager
from services.game import ResourceManager, BuffManager, ItemManager, MissionManager, BuildingManager, ResearchManager, UnitManager, HeroManager , ShopManager

class LoginManager:
    """
    통합 사용자 로그인 서비스
    
    역할: 로그인 시 필요한 모든 데이터 로드 조율 (오케스트레이터)
    - 각 Manager에게 데이터 로드 위임
    - 각 Manager가 알아서 캐싱 처리
    - 진행 중인 작업 Redis 큐 등록
    """
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None

    async def handle_user_login(self) -> Dict[str, Any]:
        """
        사용자 로그인 처리
        
        Args:
            user_no: 사용자 번호
            
        Returns:
            로그인 결과 딕셔너리
        """
        user_no = self.user_no
        
        if not user_no or not isinstance(user_no, int):
            return {"success": False, "message": "Invalid user_no"}
        
        try:
            self.logger.info(f"Login started for user {user_no}")
            
            # 1. 모든 Manager 생성
            managers = self._create_managers(user_no)
            
            # 2. 모든 데이터 로드 (병렬) - 각 Manager가 알아서 캐싱
            data = await self._load_all_data(managers)
            
            # 3. 진행 중인 작업 Redis 큐에 등록 (병렬)
            await self._register_all_active_tasks(user_no, managers)
            
            # 4. 결과 집계
            total_items = sum(
                len(v) if isinstance(v, (dict, list)) else 0 
                for v in data.values()
            )
            
            self.logger.info(f"Login completed for user {user_no}: {total_items} items loaded")
            
            return {
                "success": True,
                "message": f"Login successful. Loaded {total_items} total items",
                "data": data
            }
            
        except Exception as e:
            self.logger.error(f"Login error for user {user_no}: {e}", exc_info=True)
            return {"success": False, "message": f"Login failed: {str(e)}"}
    
    def _create_manager_instance(self, user_no: int, manager_class, key: str, managers: Dict):
        try:
            manager = manager_class(self.db_manager, self.redis_manager)
            manager.user_no = user_no
            managers[key] = manager
        except Exception as e:
            self.logger.warning(f"{manager_class.__name__} not available: {e}")
    
    # [2] _create_managers 함수 변경
    def _create_managers(self, user_no: int) -> Dict[str, Any]:
        managers = {}
        
        MANAGERS_TO_CREATE = {
            'building': BuildingManager,
            'unit': UnitManager,
            'research': ResearchManager,
            'resource': ResourceManager,
            'buff': BuffManager, # Buff Manager 추가
            'item': ItemManager,
            'mission': MissionManager,
            "shop": ShopManager
        }
        
        for key, manager_class in MANAGERS_TO_CREATE.items():
            self._create_manager_instance(user_no, manager_class, key, managers)
        
        return managers
    
    async def _load_all_data(self, managers: Dict[str, Any]) -> Dict[str, Any]:
        """
        모든 게임 데이터 로드
        - 1단계: 기본 데이터 병렬 로드
        - 2단계: 기본 데이터에 의존하는 것들 병렬 로드 (buff, mission)
        """
        
        # 1단계: 기본 데이터 병렬 로드
        PHASE1_CONFIG = {
            'building': [('building_info', 'buildings')],
            'unit': [('unit_info', 'units')],
            'research': [('research_info', 'researches')],
            'resource': [('resource_info', 'resources')],
            'item': [('item_info', 'items')],
            'shop': [('shop_info', 'shops')],
        }
        
        tasks = []
        task_names = []
        
        for manager_key, tasks_to_run in PHASE1_CONFIG.items():
            manager = managers.get(manager_key)
            if manager:
                for method_name, result_name in tasks_to_run:
                    try:
                        load_method = getattr(manager, method_name)
                        tasks.append(load_method())
                        task_names.append(result_name)
                    except AttributeError:
                        self.logger.error(f"Manager {manager_key} is missing expected method: {method_name}")
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data = {}
        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                self.logger.error(f"Error loading {name}: {result}")
                data[name] = {}
            else:
                data[name] = result if result else {}
        
        # 2단계: 의존성 있는 데이터 병렬 로드
        PHASE2_CONFIG = {
            'buff': [('buff_info', 'buffs')],
            'mission': [('mission_info', 'missions')],
        }
        
        tasks2 = []
        task_names2 = []
        
        for manager_key, tasks_to_run in PHASE2_CONFIG.items():
            manager = managers.get(manager_key)
            if manager:
                for method_name, result_name in tasks_to_run:
                    try:
                        load_method = getattr(manager, method_name)
                        tasks2.append(load_method())
                        task_names2.append(result_name)
                    except AttributeError:
                        self.logger.error(f"Manager {manager_key} is missing expected method: {method_name}")
        
        results2 = await asyncio.gather(*tasks2, return_exceptions=True)
        
        for name, result in zip(task_names2, results2):
            if isinstance(result, Exception):
                self.logger.error(f"Error loading {name}: {result}")
                data[name] = {}
            else:
                data[name] = result if result else {}
        
        return data
    
    async def _register_all_active_tasks(self, user_no: int, managers: Dict[str, Any]):
        """
        진행 중인 모든 작업을 Redis 완료 큐에 등록 (병렬)
        
        Args:
            user_no: 사용자 번호
            managers: Manager 딕셔너리
        """
        tasks = []
        
        # 빌딩 매니저의 register_building_tasks 호출
        
        
        # Unit, Research, Buff 작업 등록
        tasks.extend([
            self._register_unit_tasks(user_no),
            self._register_research_tasks(user_no),
            #self._register_buff_tasks(user_no)
        ])
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _register_unit_tasks(self, user_no: int):
        """
        진행 중인 유닛 생산 작업을 완료 큐에 등록
        
        Args:
            user_no: 사용자 번호
        """
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            
            await unit_redis.register_active_tasks_to_queue(
                user_no,
                self.db_manager,
                None
            )
            
            self.logger.debug(f"Registered unit tasks for user {user_no}")
            
        except AttributeError:
            self.logger.debug(f"Unit task registration not available")
        except Exception as e:
            self.logger.error(f"Error registering unit tasks for user {user_no}: {e}")
    
    async def _register_research_tasks(self, user_no: int):
        """
        진행 중인 연구 작업을 완료 큐에 등록
        
        Args:
            user_no: 사용자 번호
        """
        try:
            research_redis = self.redis_manager.get_research_manager()
            
            await research_redis.register_active_tasks_to_queue(
                user_no,
                self.db_manager,
                None
            )
            
            self.logger.debug(f"Registered research tasks for user {user_no}")
            
        except AttributeError:
            self.logger.debug(f"Research task registration not available")
        except Exception as e:
            self.logger.error(f"Error registering research tasks for user {user_no}: {e}")
    
    async def _register_buff_tasks(self, user_no: int):
        """
        활성 버프를 완료 큐에 등록
        
        Args:
            user_no: 사용자 번호
        """
        try:
            buff_redis = self.redis_manager.get_buff_manager()
            
            await buff_redis.register_active_tasks_to_queue(
                user_no,
                self.db_manager,
                None
            )
            
            self.logger.debug(f"Registered buff tasks for user {user_no}")
            
        except AttributeError:
            self.logger.debug(f"Buff task registration not available")
        except Exception as e:
            self.logger.error(f"Error registering buff tasks for user {user_no}: {e}")