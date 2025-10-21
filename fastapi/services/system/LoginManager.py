# services/comprehensive_login_service.py
from typing import Dict, Any
import logging
import asyncio
from datetime import datetime

from services.redis_manager import RedisManager
from services.db_manager import DBManager
from services.game import BuildingManager, UnitManager, ResearchManager, ResourceManager


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
    
    def _create_managers(self, user_no: int) -> Dict[str, Any]:
        """
        모든 Game Manager 생성
        
        Args:
            user_no: 사용자 번호
            
        Returns:
            Manager 딕셔너리
        """
        managers = {}
        
        # Building Manager
        building_manager = BuildingManager(self.db_manager, self.redis_manager)
        building_manager.user_no = user_no
        managers['building'] = building_manager
        
        # # Unit Manager
        # try:
        #     unit_manager = UnitManager(self.db_manager, self.redis_manager)
        #     unit_manager.user_no = user_no
        #     managers['unit'] = unit_manager
        # except Exception as e:
        #     self.logger.warning(f"UnitManager not available: {e}")
        
        # # Research Manager
        # try:
        #     research_manager = ResearchManager(self.db_manager, self.redis_manager)
        #     research_manager.user_no = user_no
        #     managers['research'] = research_manager
        # except Exception as e:
        #     self.logger.warning(f"ResearchManager not available: {e}")
        
        # # Resource Manager
        # try:
        #     resource_manager = ResourceManager(self.db_manager, self.redis_manager)
        #     resource_manager.user_no = user_no
        #     managers['resource'] = resource_manager
        # except Exception as e:
        #     self.logger.warning(f"ResourceManager not available: {e}")
        
        return managers
    
    async def _load_all_data(self, managers: Dict[str, Any]) -> Dict[str, Any]:
        """
        모든 게임 데이터 로드 (병렬)
        
        각 Manager의 get 메서드 호출
        → 각 Manager가 알아서 캐싱 처리 (메모리 → Redis → DB)
        
        Args:
            managers: Manager 딕셔너리
            
        Returns:
            로드된 데이터 딕셔너리
        """
        tasks = []
        task_names = []
        
        # Building
        if 'building' in managers:
            tasks.append(managers['building'].get_user_buildings())
            task_names.append('buildings')
        
        # Unit
        if 'unit' in managers:
            tasks.append(managers['unit'].get_user_units())
            task_names.append('units')
        
        # Research
        if 'research' in managers:
            tasks.append(managers['research'].get_user_research())
            task_names.append('research')
        
        # Resource
        if 'resource' in managers:
            tasks.append(managers['resource'].get_user_resources())
            task_names.append('resources')
        
        # 병렬 실행
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 결과 정리
        data = {}
        for name, result in zip(task_names, results):
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
        if 'building' in managers:
            tasks.append(managers['building'].register_building_tasks(user_no))
        
        # Unit, Research, Buff 작업 등록
        tasks.extend([
            self._register_unit_tasks(user_no),
            self._register_research_tasks(user_no),
            self._register_buff_tasks(user_no)
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