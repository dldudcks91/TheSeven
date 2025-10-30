# UnitManager.py
from sqlalchemy.orm import Session
import models, schemas
from services.system.GameDataManager import GameDataManager
from services.game import ResourceManager, BuffManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime, timedelta
import logging

'''
task_type 값
0: 훈련 (TASK_TRAIN)
1: 업그레이드 (TASK_UPGRADE)

status 값
0: 완료됨
1: 진행중 (TASK_PROCESSING)
'''
class UnitManager():
    CONFIG_TYPE = 'unit'
    
    # 작업 상태 상수
    TASK_PROCESSING = 1
    TASK_COMPLETED = 0
    
    # 작업 타입 상수
    TASK_TRAIN = 0
    TASK_UPGRADE = 1
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_units = None
        self.logger = logging.getLogger(self.__class__.__name__)
        
    @property
    def user_no(self):
        """사용자 번호의 getter"""
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        """사용자 번호의 setter. 정수형인지 확인"""
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_units = None

    @property
    def data(self):
        """요청 데이터의 getter"""
        return self._data

    @data.setter
    def data(self, value: dict):
        """요청 데이터의 setter. 딕셔너리인지 확인"""
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
        
    def _validate_input(self):
        """공통 입력값 검증"""
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }
        
        unit_idx = self.data.get('unit_idx')
        if not unit_idx:
            return {
                "success": False,
                "message": f"Missing required fields: unit_idx: {unit_idx}",
                "data": {}
            }
        
        return None
    
    def _format_unit_for_cache(self, unit_data):
        """캐시용 유닛 데이터 포맷팅"""
        try:
            if isinstance(unit_data, dict):
                return {
                    "id": unit_data.get('id'),
                    "user_no": unit_data.get('user_no'),
                    "unit_idx": unit_data.get('unit_idx'),
                    "total": unit_data.get('total'),
                    "ready": unit_data.get('ready'),
                    "field": unit_data.get('field'),
                    "injured": unit_data.get('injured'),
                    "wounded": unit_data.get('wounded'),
                    "healing": unit_data.get('healing'),
                    "death": unit_data.get('death'),
                    "training": unit_data.get('training'),
                    "upgrading": unit_data.get('upgrading'),
                    "cached_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "id": unit_data.id,
                    "user_no": unit_data.user_no,
                    "unit_idx": unit_data.unit_idx,
                    "total": unit_data.total,
                    "ready": unit_data.ready,
                    "field": unit_data.field,
                    "injured": unit_data.injured,
                    "wounded": unit_data.wounded,
                    "healing": unit_data.healing,
                    "death": unit_data.death,
                    "training": unit_data.training,
                    "upgrading": unit_data.upgrading,
                    "cached_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            self.logger.error(f"Error formatting unit data for cache: {e}")
            return {}
    
    async def get_user_units(self):
        """사용자 유닛 데이터를 캐시 우선으로 조회"""
        if self._cached_units is not None:
            return self._cached_units
        
        user_no = self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            unit_redis = self.redis_manager.get_unit_manager()
            self._cached_units = await unit_redis.get_cached_units(user_no)
            self.logger.debug(self._cached_units)
            if self._cached_units:
                self.logger.debug(f"Cache hit: Retrieved {self._cached_units} units for user {user_no}")
                return self._cached_units
            
            # 2. 캐시 미스: DB에서 조회
            units_data = self.get_db_units(user_no)
            
            if units_data['success'] and units_data['data']:
                # 3. Redis에 캐싱
                cache_success = await unit_redis.cache_user_units_data(user_no, units_data['data'])
                if cache_success:
                    self.logger.debug(f"Successfully cached {units_data['data']} units for user {user_no}")
                
                self._cached_units = units_data['data']
            else:
                self._cached_units = {}
                
        except Exception as e:
            self.logger.error(f"Error getting user units for user {user_no}: {e}")
            self._cached_units = {}
        
        return self._cached_units
    
    def get_db_units(self, user_no):
        """DB에서 유닛 데이터만 순수하게 조회"""
        try:
            unit_db = self.db_manager.get_unit_manager()
            units_result = unit_db.get_user_units(user_no)
            
            if not units_result['success']:
                return units_result
            
            # 데이터 포맷팅
            formatted_units = {}
            for unit in units_result['data']:
                unit_idx = unit['unit_idx']
                formatted_units[str(unit_idx)] = self._format_unit_for_cache(unit)
            
            return {
                "success": True,
                "message": f"Loaded {len(formatted_units)} units from database",
                "data": formatted_units
            }
            
        except Exception as e:
            self.logger.error(f"Error loading units from DB for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    def invalidate_user_unit_cache(self, user_no: int):
        """사용자 유닛 캐시 무효화"""
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            cache_invalidated = unit_redis.invalidate_unit_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_units = None
            
            self.logger.debug(f"Cache invalidated for user {user_no}: {cache_invalidated}")
            return cache_invalidated
            
        except Exception as e:
            self.logger.error(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    async def _format_unit_data(self, unit_idx):
        """유닛 데이터를 응답 형태로 포맷팅 (캐시에서 조회)"""
        units_data = await self.get_user_units()
        unit = units_data.get(str(unit_idx))
        
        if not unit:
            return None
        
        # Redis에서 실제 완료 시간을 조회 (서버에서 관리하는 시간)
        redis_completion_time = None
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            redis_completion_time = await unit_redis.get_unit_completion_time(
                self.user_no, unit_idx
            )
        except Exception as redis_error:
            self.logger.error(f"Redis error: {redis_error}")
        
        return {
            **unit,
            "task_completion_time": redis_completion_time.isoformat() if redis_completion_time else None
        }
    
    def _get_unit(self, user_no, unit_idx):
        """유닛 조회"""
        unit_db = self.db_manager.get_unit_manager()
        return unit_db.get_unit(user_no, unit_idx)
    
    def _get_all_user_units(self, user_no):
        """사용자의 모든 유닛 조회"""
        unit_db = self.db_manager.get_unit_manager()
        return unit_db.get_all_user_units(user_no)
    
    def _get_current_task(self, user_no, unit_idx):
        """현재 진행중인 작업 반환"""
        unit_db = self.db_manager.get_unit_manager()
        return unit_db.get_current_task(user_no, unit_idx)
    
    async def _ensure_unit_exists(self, user_no: int, unit_idx: int) -> dict:
        """유닛 데이터 존재 확인 및 생성"""
        units_data = await self.get_user_units()
        unit = units_data.get(str(unit_idx))
        
        if unit:
            return unit
        
        # 없으면 생성
        self.logger.info(f"Creating initial unit data for user {user_no}, unit {unit_idx}")
        
        unit_db = self.db_manager.get_unit_manager()
        create_result = unit_db.create_unit(
            user_no=user_no,
            unit_idx=unit_idx,
            total=0,
            ready=0,
            field=0,
            injured=0,
            wounded=0,
            healing=0,
            death=0,
            training=0,
            upgrading=0
        )
        
        if not create_result['success']:
            raise Exception("Failed to create unit")
        
        self.db_manager.commit()
        
        # 캐시 갱신
        new_unit = self._format_unit_for_cache(create_result['data'])
        await self._update_cached_unit(user_no, unit_idx, new_unit)
        
        return new_unit
    
    async def _has_ongoing_task(self, user_no, unit_idxs):
        """해당 유닛 타입에 진행중인 작업이 있는지 확인 (Redis 기반)"""
        if not isinstance(unit_idxs, list):
            unit_idxs = [unit_idxs]
        
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            for unit_idx in unit_idxs:
                completion_time = await unit_redis.get_unit_completion_time(user_no, unit_idx)
                if completion_time:
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Error checking ongoing task in Redis: {e}")
            # Redis 실패시 DB 확인
            unit_db = self.db_manager.get_unit_manager()
            return unit_db.has_ongoing_task(user_no, unit_idxs)
    
    async def _handle_resource_transaction(self, user_no, unit_idx, quantity=1):
        """자원 체크 및 소모를 한번에 처리"""
        try:
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][unit_idx]
            costs = required['cost']
            base_time = required['time']
            
            # 수량에 따른 총 비용 계산
            total_costs = {}
            for resource, cost in costs.items():
                total_costs[resource] = cost * quantity
            
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            if not await resource_manager.check_require_resources(user_no, total_costs):
                return None, "Need More Resources"
            
            await resource_manager.consume_resources(user_no, total_costs)
            return base_time, None
            
        except Exception as e:
            return None, f"Resource error: {str(e)}"
    
    def _apply_unit_buffs(self, user_no, base_time, task_type):
        """유닛 훈련/업그레이드 시간 버프 적용"""
        try:
            buff_manager = BuffManager(self.db_manager, self.redis_manager)
            
            # 작업 타입에 따른 버프 조회
            if task_type == self.TASK_TRAIN:
                buffs = buff_manager.get_active_buffs(user_no, 'unit_train_speed')
            elif task_type == self.TASK_UPGRADE:
                buffs = buff_manager.get_active_buffs(user_no, 'unit_upgrade_speed')
            else:
                return base_time
            
            total_reduction = 0
            for buff in buffs:
                total_reduction += buff.get('reduction_percent', 0)
            
            # 최대 90% 단축으로 제한
            total_reduction = min(total_reduction, 90)
            
            # 시간 단축 적용
            reduced_time = base_time * (1 - total_reduction / 100)
            return max(1, int(reduced_time))  # 최소 1초
            
        except Exception as e:
            self.logger.error(f"Error applying unit buffs: {e}")
            return base_time
    
    async def _update_cached_unit(self, user_no: int, unit_idx: int, updated_data: dict):
        """캐시된 유닛 데이터 업데이트"""
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            cache_updated = await unit_redis.update_cached_unit(user_no, unit_idx, updated_data)
            
            return cache_updated
            
        except Exception as e:
            self.logger.error(f"Error updating cached unit {unit_idx} for user {user_no}: {e}")
            return False
    
    async def unit_info(self):
        """
        유닛 정보를 조회합니다.
        """
        try:
            units_data = await self.get_user_units()
            
            # 각 유닛에 task_completion_time 추가
            enriched_units = {}
            for unit_idx, unit in units_data.items():
                formatted = await self._format_unit_data(int(unit_idx))
                if formatted:
                    enriched_units[unit_idx] = formatted
            
            return {
                "success": True,
                "message": f"Retrieved {len(enriched_units)} units",
                "data": enriched_units
            }
        except Exception as e:
            self.logger.error(f"Error getting unit info: {e}")
            return {
                "success": False,
                "message": f"Error retrieving unit info: {str(e)}",
                "data": {}
            }
    
    async def unit_train(self):
        """유닛을 훈련합니다."""
        try:
            user_no = self.user_no
            
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            unit_idx = self.data.get('unit_idx')
            quantity = int(self.data.get('quantity', 1))
            
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            if await self._has_ongoing_task(user_no, unit_idx):
                return {"success": False, "message": "Another task is already in progress for this unit type", "data": {}}
            
            # 유닛 존재 확인 및 생성
            unit = await self._ensure_unit_exists(user_no, unit_idx)
            
            # 자원 처리
            base_time, error_msg = await self._handle_resource_transaction(user_no, unit_idx, quantity)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 버프 적용된 시간 계산
            train_time = self._apply_unit_buffs(user_no, base_time * quantity, self.TASK_TRAIN)
            
            # 시간 설정
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=train_time)
            
            # Redis 완료 큐에 추가
            unit_redis = self.redis_manager.get_unit_manager()
            await unit_redis.add_unit_to_queue(user_no, unit_idx, completion_time, unit_count=quantity)
            
            # Redis 캐시 업데이트
            updated_unit = {
                **unit,
                'training': unit.get('training', 0) + quantity,
                'total': unit.get('total', 0) + quantity,
                'cached_at': datetime.utcnow().isoformat()
            }
            await self._update_cached_unit(user_no, unit_idx, updated_unit)
            
            return {
                "success": True,
                "message": f"Started training {quantity} units. Will complete in {train_time} seconds",
                "data": await self._format_unit_data(unit_idx)
            }
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error training unit: {e}")
            return {"success": False, "message": f"Error training unit: {str(e)}", "data": {}}
    
    async def unit_upgrade(self):
        """
        유닛을 업그레이드합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            unit_idx = self.data.get('unit_idx')
            quantity = int(self.data.get('quantity', 1))
            target_unit_idx = self.data.get('target_unit_idx')
            
            if not target_unit_idx:
                return {"success": False, "message": "Missing target_unit_idx", "data": {}}
            
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            # 진행중인 작업이 있는지 확인
            if await self._has_ongoing_task(user_no, unit_idx):
                return {"success": False, "message": "Another task is already in progress for this unit type", "data": {}}
            
            # 캐시에서 유닛 정보 조회
            units_data = await self.get_user_units()
            unit = units_data.get(str(unit_idx))
            if not unit:
                return {"success": False, "message": "Unit not found", "data": {}}
            
            if unit.get('ready', 0) < quantity:
                return {"success": False, "message": f"Not enough ready units. Available: {unit.get('ready', 0)}", "data": {}}
            
            # 자원 처리 (타겟 유닛 기준)
            base_time, error_msg = await self._handle_resource_transaction(user_no, target_unit_idx, quantity)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 버프 적용된 시간 계산
            upgrade_time = self._apply_unit_buffs(user_no, base_time * quantity, self.TASK_UPGRADE)
            
            # 시간 설정
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=upgrade_time)
            
            # Redis 완료 큐에 추가 (Task 생성)
            unit_redis = self.redis_manager.get_unit_manager()
            await unit_redis.add_unit_to_queue(user_no, unit_idx, completion_time, unit_count=quantity)
            
            # Redis 캐시 업데이트 (ready 감소, upgrading 증가)
            updated_unit = {
                **unit,
                'ready': unit.get('ready', 0) - quantity,
                'upgrading': unit.get('upgrading', 0) + quantity,
                'cached_at': datetime.utcnow().isoformat()
            }
            await self._update_cached_unit(user_no, unit_idx, updated_unit)
            
            return {
                "success": True,
                "message": f"Started upgrade of {quantity} units to {target_unit_idx}. Will complete in {upgrade_time} seconds",
                "data": await self._format_unit_data(unit_idx)
            }
            
        except Exception as e:
            self.logger.error(f"Error upgrading unit: {e}")
            return {"success": False, "message": f"Error upgrading unit: {str(e)}", "data": {}}
    
    async def unit_cancel(self):
        """
        유닛 훈련/업그레이드를 취소합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            unit_idx = self.data.get('unit_idx')
            
            # 캐시에서 유닛 정보 조회
            units_data = await self.get_user_units()
            unit = units_data.get(str(unit_idx))
            if not unit:
                return {"success": False, "message": "Unit not found", "data": {}}
            
            # DB에서 작업 정보 조회 (task_type, quantity 확인용)
            task = self._get_current_task(user_no, unit_idx)
            if not task:
                return {"success": False, "message": "No task to cancel", "data": {}}
            
            # Redis 큐에서 제거
            unit_redis = self.redis_manager.get_unit_manager()
            await unit_redis.remove_unit(user_no, unit_idx)
            
            # 자원 환불 처리
            try:
                if task.task_type == self.TASK_UPGRADE:
                    required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][task.target_unit_idx]
                else:
                    required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][unit_idx]
                
                costs = required['cost']
                refund_costs = {}
                for resource, cost in costs.items():
                    refund_costs[resource] = int(cost * task.quantity)
                
                resource_manager = ResourceManager(self.db_manager, self.redis_manager)
                await resource_manager.produce_resources(user_no, refund_costs)
                
            except Exception as refund_error:
                self.logger.error(f"Refund failed: {refund_error}")
            
            # Redis 캐시 업데이트
            updated_unit = {**unit}
            if task.task_type == self.TASK_UPGRADE:
                # 업그레이드 취소: ready 증가, upgrading 감소
                updated_unit['ready'] = unit.get('ready', 0) + task.quantity
                updated_unit['upgrading'] = unit.get('upgrading', 0) - task.quantity
            else:
                # 훈련 취소: training 감소, total 감소
                updated_unit['training'] = unit.get('training', 0) - task.quantity
                updated_unit['total'] = unit.get('total', 0) - task.quantity
            
            updated_unit['cached_at'] = datetime.utcnow().isoformat()
            await self._update_cached_unit(user_no, unit_idx, updated_unit)
            
            message = "Unit training cancelled" if task.task_type == self.TASK_TRAIN else "Unit upgrade cancelled"
            
            return {
                "success": True,
                "message": f"{message}, resources refunded",
                "data": await self._format_unit_data(unit_idx)
            }
            
        except Exception as e:
            self.logger.error(f"Error cancelling unit task: {e}")
            return {"success": False, "message": f"Error cancelling unit task: {str(e)}", "data": {}}
    
    async def unit_speedup(self):
        """
        유닛 훈련/업그레이드를 즉시 완료합니다. (아이템 사용)
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            unit_idx = self.data.get('unit_idx')
            
            unit = self._get_unit(user_no, unit_idx)
            if not unit:
                return {"success": False, "message": "Unit not found", "data": {}}
            
            task = self._get_current_task(user_no, unit_idx)
            if not task:
                return {"success": False, "message": "No task in progress", "data": {}}
            
            # Redis에서 완료 시간 조회
            unit_redis = self.redis_manager.get_unit_manager()
            completion_time = await unit_redis.get_unit_completion_time(user_no, unit_idx)
            if not completion_time:
                return {"success": False, "message": "Unit completion time not found", "data": {}}
            
            # 즉시 완료를 위해 현재 시간으로 업데이트
            current_time = datetime.utcnow()
            await unit_redis.update_unit_completion_time(user_no, unit_idx, current_time)
            
            return {
                "success": True,
                "message": "Unit task completion time accelerated. Will complete shortly.",
                "data": await self._format_unit_data(unit_idx)
            }
            
        except Exception as e:
            self.logger.error(f"Error speeding up unit task: {e}")
            return {"success": False, "message": f"Error speeding up unit task: {str(e)}", "data": {}}
    
    async def get_completion_status(self):
        """
        현재 진행 중인 유닛 작업들의 완료 상태를 조회합니다.
        """
        try:
            user_no = self.user_no
            
            # 진행 중인 작업들 조회
            unit_db = self.db_manager.get_unit_manager()
            active_tasks = unit_db.get_active_tasks(user_no)
            
            completion_info = []
            current_time = datetime.utcnow()
            
            for task in active_tasks:
                unit_redis = self.redis_manager.get_unit_manager()
                redis_completion_time = await unit_redis.get_unit_completion_time(
                    user_no, task['unit_idx']
                )
                
                if redis_completion_time:
                    remaining_seconds = max(0, int((redis_completion_time - current_time).total_seconds()))
                    completion_info.append({
                        "unit_idx": task['unit_idx'],
                        "task_type": task['task_type'],
                        "quantity": task['quantity'],
                        "target_unit_idx": task['target_unit_idx'],
                        "completion_time": redis_completion_time.isoformat(),
                        "remaining_seconds": remaining_seconds,
                        "is_ready": remaining_seconds == 0
                    })
            
            return {
                "success": True,
                "message": f"Retrieved completion status for {len(completion_info)} unit tasks",
                "data": completion_info
            }
            
        except Exception as e:
            self.logger.error(f"Error getting completion status: {e}")
            return {"success": False, "message": f"Error getting completion status: {str(e)}", "data": []}
    
    # ===== ✨ 워커용 메서드 추가 =====
    
    async def finish_unit_production(self, user_no: int, unit_idx: int, task_id: str):
        """
        유닛 생산 완료 처리 (Worker에서 호출, Redis 캐시만 업데이트)
        
        비즈니스 로직:
        1. Task 검증
        2. training/upgrading → ready로 이동
        3. Task 삭제
        4. DB 동기화 큐 추가
        """
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            
            # 1. Redis에서 Task 정보 조회
            task_data = await unit_redis.get_task_data(task_id)
            
            if not task_data:
                self.logger.warning(f"Task not found: {task_id}")
                return None
            
            # Task 검증
            if task_data.get('user_no') != user_no:
                self.logger.warning(f"Task user mismatch: {task_id}")
                return None
            
            if task_data.get('unit_idx') != unit_idx:
                self.logger.warning(f"Task unit_idx mismatch: {task_id}")
                return None
            
            quantity = int(task_data.get('quantity', 0))
            task_type = int(task_data.get('task_type', self.TASK_TRAIN))
            target_unit_idx = task_data.get('target_unit_idx')
            
            if quantity <= 0:
                self.logger.warning(f"Invalid quantity in task: {task_id}")
                return None
            
            # 2. 캐시에서 유닛 정보 조회
            self._user_no = user_no  # 임시로 설정
            units_data = await self.get_user_units()
            unit = units_data.get(str(unit_idx))
            
            if not unit:
                self.logger.warning(f"Unit not found in cache: user_no={user_no}, unit_idx={unit_idx}")
                return None
            
            # 3. 비즈니스 로직에 따라 Redis 캐시 업데이트
            updated_unit = {**unit}
            
            if task_type == self.TASK_TRAIN:
                # 훈련 완료: training → ready
                updated_unit['training'] = max(0, unit.get('training', 0) - quantity)
                updated_unit['ready'] = unit.get('ready', 0) + quantity
                action = "training"
                
            elif task_type == self.TASK_UPGRADE:
                # 업그레이드 완료: upgrading → ready (타겟 유닛으로)
                updated_unit['upgrading'] = max(0, unit.get('upgrading', 0) - quantity)
                updated_unit['total'] = max(0, unit.get('total', 0) - quantity)
                
                # 타겟 유닛 증가
                if target_unit_idx:
                    target_unit = units_data.get(str(target_unit_idx))
                    if target_unit:
                        updated_target = {
                            **target_unit,
                            'total': target_unit.get('total', 0) + quantity,
                            'ready': target_unit.get('ready', 0) + quantity,
                            'cached_at': datetime.utcnow().isoformat()
                        }
                        await self._update_cached_unit(user_no, target_unit_idx, updated_target)
                
                action = "upgrade"
            else:
                self.logger.warning(f"Unknown task_type: {task_type}")
                return None
            
            updated_unit['cached_at'] = datetime.utcnow().isoformat()
            
            # 4. Redis 캐시 업데이트
            await self._update_cached_unit(user_no, unit_idx, updated_unit)
            
            # 5. Task 삭제
            await unit_redis.remove_task(user_no, task_id)
            await unit_redis.remove_from_completed_queue(user_no, task_id)
            
            # 6. DB 동기화 큐에 추가
            sync_data = {
                'type': f'unit_{action}_complete',
                'unit_idx': unit_idx,
                'quantity': quantity,
                'task_type': task_type,
                'target_unit_idx': target_unit_idx,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            await unit_redis.add_to_sync_queue(user_no, unit_idx, sync_data)
            
            self.logger.info(f"Unit {action} completed in cache: user_no={user_no}, "
                           f"unit_idx={unit_idx}, quantity={quantity}")
            
            return {
                'success': True,
                'quantity': quantity,
                'task_id': task_id,
                'action': action
            }
            
        except Exception as e:
            self.logger.error(f"Error in finish_unit_production: {e}")
            return None