# UnitManager.py
from sqlalchemy.orm import Session
import models, schemas
from services.system import GameDataManager
from services.game import ResourceManager, BuffManager
from services.redis_manager import RedisManager
from datetime import datetime, timedelta

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
    
    def __init__(self, db: Session, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db = db
        self.redis_manager = redis_manager
        
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
    
    def _format_unit_data(self, unit):
        """유닛 데이터를 응답 형태로 포맷팅"""
        # Redis에서 실제 완료 시간을 조회 (서버에서 관리하는 시간)
        redis_completion_time = None
        task = self._get_current_task(unit.user_no, unit.unit_idx)
        
        if task:  # 진행중인 작업이 있는 경우
            try:
                unit_redis = self.redis_manager.get_unit_manager()
                redis_completion_time = unit_redis.get_unit_completion_time(
                    unit.user_no, unit.unit_idx
                )
            except Exception as redis_error:
                print(f"Redis error: {redis_error}")
        
        return {
            "id": unit.id,
            "user_no": unit.user_no,
            "unit_idx": unit.unit_idx,
            "total": unit.total,
            "ready": unit.ready,
            "field": unit.field,
            "injured": unit.injured,
            "wounded": unit.wounded,
            "healing": unit.healing,
            "death": unit.death,
            "training": unit.training,
            "upgrading": unit.upgrading,
            "task_completion_time": redis_completion_time.isoformat() if redis_completion_time else None
        }
    
    def _get_unit(self, user_no, unit_idx):
        """유닛 조회"""
        return self.db.query(models.Unit).filter(
            models.Unit.user_no == user_no,
            models.Unit.unit_idx == unit_idx
        ).first()
    
    def _get_all_user_units(self, user_no):
        """사용자의 모든 유닛 조회"""
        return self.db.query(models.Unit).filter(
            models.Unit.user_no == user_no
        ).all()
    
    def _get_current_task(self, user_no, unit_idx):
        """현재 진행중인 작업 반환"""
        return self.db.query(models.UnitTasks).filter(
            models.UnitTasks.user_no == user_no,
            models.UnitTasks.unit_idx == unit_idx,
            models.UnitTasks.status == self.TASK_PROCESSING
        ).first()
    
    def _has_ongoing_task(self, user_no, unit_idxs):
        """해당 유닛 타입에 진행중인 작업이 있는지 확인"""
        if not isinstance(unit_idxs, list):
            unit_idxs = [unit_idxs]
            
        task = self.db.query(models.UnitTasks).filter(
            models.UnitTasks.user_no == user_no,
            models.UnitTasks.unit_idx.in_(unit_idxs),
            models.UnitTasks.status == self.TASK_PROCESSING
        ).first()
        return task is not None
    
    def _handle_resource_transaction(self, user_no, unit_idx, quantity=1):
        """자원 체크 및 소모를 한번에 처리"""
        try:
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][unit_idx]
            costs = required['cost']
            base_time = required['time']
            
            # 수량에 따른 총 비용 계산
            total_costs = {}
            for resource, cost in costs.items():
                total_costs[resource] = cost * quantity
            
            resource_manager = ResourceManager(self.db)
            if not resource_manager.check_require_resources(user_no, total_costs):
                return None, "Need More Resources"
            
            resource_manager.consume_resources(user_no, total_costs)
            return base_time, None
            
        except Exception as e:
            return None, f"Resource error: {str(e)}"
    
    def _apply_unit_buffs(self, user_no, base_time, task_type):
        """유닛 훈련/업그레이드 시간 버프 적용"""
        try:
            buff_manager = BuffManager(self.db)
            
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
            print(f"Error applying unit buffs: {e}")
            return base_time
    
    def _update_unit_counts(self, unit):
        """유닛 총합 개수 업데이트"""
        calculated_total = (unit.ready + unit.field + unit.injured + 
                           unit.wounded + unit.healing + unit.death + 
                           unit.training + unit.upgrading)
        if unit.total != calculated_total:
            unit.total = calculated_total
    
    def unit_info(self):
        """
        유닛 정보를 조회합니다.
        """
        try:
            user_no = self.user_no
            
            user_units = self._get_all_user_units(user_no)
            units_data = {}
            
            for unit in user_units:
                units_data[unit.unit_idx] = self._format_unit_data(unit)
            
            return {
                "success": True,
                "message": f"Retrieved {len(units_data)} unit types",
                "data": units_data
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving units info: {str(e)}", "data": {}}
    
    def unit_train(self):
        """
        유닛을 훈련합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            unit_idx = self.data.get('unit_idx')
            
            try:
                quantity = int(self.data.get('quantity', 0))
            except:
                return {"success": False, "message": "Quantity must be Integer", "data": {}}
                
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            # 유닛 설정 확인
            unit_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]
            if unit_idx not in unit_config:
                return {"success": False, "message": "Invalid unit type", "data": {}}
            
            # 같은 카테고리의 유닛들이 작업중인지 확인
            unit_category = unit_config[unit_idx]['category']
            unit_idxs = [key for key, value in unit_config.items() if value['category'] == unit_category]
            
            if self._has_ongoing_task(user_no, unit_idxs):
                return {"success": False, "message": "Another task is already in progress for this unit category", "data": {}}
            
            # 유닛 조회 또는 생성
            unit = self._get_unit(user_no, unit_idx)
            if not unit:
                unit = models.Unit(
                    user_no=user_no,
                    unit_idx=unit_idx,
                    total=0, ready=0, field=0, injured=0, wounded=0, 
                    healing=0, death=0, training=0, upgrading=0
                )
                self.db.add(unit)
                self.db.flush()
            
            # 최대 개수 체크
            config = unit_config[unit_idx]
            max_count = config.get('max_count', 999)
            if unit.total + quantity > max_count:
                return {"success": False, "message": f"Max {max_count} units allowed", "data": {}}
            
            # 자원 처리
            base_time, error_msg = self._handle_resource_transaction(user_no, unit_idx, quantity)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 버프 적용된 시간 계산
            train_time = self._apply_unit_buffs(user_no, base_time * quantity, self.TASK_TRAIN)
            
            # 시간 설정
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=train_time)
            
            # 작업 생성 (DB에는 end_time 저장하지 않음)
            task = models.UnitTasks(
                user_no=user_no,
                unit_idx=unit_idx,
                task_type=self.TASK_TRAIN,
                quantity=quantity,
                target_unit_idx=None,
                status=self.TASK_PROCESSING,
                start_time=start_time,
                end_time=None,  # DB에는 저장하지 않음
                created_at=start_time
            )
            
            self.db.add(task)
            unit.training += quantity
            self._update_unit_counts(unit)
            
            self.db.commit()
            self.db.refresh(unit)
            
            # Redis 완료 큐에 추가
            unit_redis = self.redis_manager.get_unit_manager()
            unit_redis.add_unit(user_no, unit_idx, completion_time)
            
            unit_name = config.get('name', f'Unit_{unit_idx}')
            return {
                "success": True,
                "message": f"Started training {quantity} {unit_name}. Will complete in {train_time} seconds",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error training unit: {str(e)}", "data": {}}
    
    def unit_upgrade(self):
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
            target_unit_idx = self.data.get('target_unit_idx')
            
            try:
                quantity = int(self.data.get('quantity', 1))
            except:
                return {"success": False, "message": "Quantity must be Integer", "data": {}}
            
            if not target_unit_idx:
                return {"success": False, "message": "Missing target_unit_idx", "data": {}}
            
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            # 진행중인 작업이 있는지 확인
            if self._has_ongoing_task(user_no, unit_idx):
                return {"success": False, "message": "Another task is already in progress for this unit type", "data": {}}
            
            unit = self._get_unit(user_no, unit_idx)
            if not unit:
                return {"success": False, "message": "Unit not found", "data": {}}
            
            if unit.ready < quantity:
                return {"success": False, "message": f"Not enough ready units. Available: {unit.ready}", "data": {}}
            
            # 자원 처리 (타겟 유닛 기준)
            base_time, error_msg = self._handle_resource_transaction(user_no, target_unit_idx, quantity)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 버프 적용된 시간 계산
            upgrade_time = self._apply_unit_buffs(user_no, base_time * quantity, self.TASK_UPGRADE)
            
            # 시간 설정
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=upgrade_time)
            
            # 작업 생성 (DB에는 end_time 저장하지 않음)
            task = models.UnitTasks(
                user_no=user_no,
                unit_idx=unit_idx,
                task_type=self.TASK_UPGRADE,
                quantity=quantity,
                target_unit_idx=target_unit_idx,
                status=self.TASK_PROCESSING,
                start_time=start_time,
                end_time=None,  # DB에는 저장하지 않음
                created_at=start_time
            )
            
            self.db.add(task)
            unit.ready -= quantity
            unit.upgrading += quantity
            self._update_unit_counts(unit)
            
            self.db.commit()
            self.db.refresh(unit)
            
            # Redis 완료 큐에 추가
            self.redis_manager.add_unit_to_queue(user_no, unit_idx, completion_time)
            
            return {
                "success": True,
                "message": f"Started upgrade of {quantity} units to {target_unit_idx}. Will complete in {upgrade_time} seconds",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error upgrading unit: {str(e)}", "data": {}}
    
    def unit_cancel(self):
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
            
            unit = self._get_unit(user_no, unit_idx)
            if not unit:
                return {"success": False, "message": "Unit not found", "data": {}}
            
            task = self._get_current_task(user_no, unit_idx)
            if not task:
                return {"success": False, "message": "No task to cancel", "data": {}}
            
            # Redis 큐에서 제거
            unit_redis = self.redis_manager.get_unit_manager()
            unit_redis.remove_unit(user_no, unit_idx)
            
            # 자원 환불 처리
            try:
                if task.task_type == self.TASK_UPGRADE:
                    required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][task.target_unit_idx]
                    unit.ready += task.quantity
                    unit.upgrading -= task.quantity
                else:
                    unit.training -= task.quantity
                    required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][unit_idx]
                
                costs = required['cost']
                refund_costs = {}
                for resource, cost in costs.items():
                    refund_costs[resource] = int(cost * task.quantity)
                
                resource_manager = ResourceManager(self.db)
                resource_manager.produce_resources(user_no, refund_costs)
                
            except Exception as refund_error:
                print(f"Refund failed: {refund_error}")
            
            # 취소된 task 삭제
            self.db.delete(task)
            
            self._update_unit_counts(unit)
            self.db.commit()
            self.db.refresh(unit)
            
            message = "Unit training cancelled" if task.task_type == self.TASK_TRAIN else "Unit upgrade cancelled"
            
            return {
                "success": True,
                "message": f"{message}, resources refunded",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error cancelling unit task: {str(e)}", "data": {}}
    
    def unit_speedup(self):
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
            completion_time = unit_redis.get_unit_completion_time(user_no, unit_idx)
            if not completion_time:
                return {"success": False, "message": "Unit completion time not found", "data": {}}
            
            # 즉시 완료를 위해 현재 시간으로 업데이트
            current_time = datetime.utcnow()
            unit_redis.update_unit_completion_time(user_no, unit_idx, current_time)
            
            return {
                "success": True,
                "message": "Unit task completion time accelerated. Will complete shortly.",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error speeding up unit task: {str(e)}", "data": {}}
    
    def get_completion_status(self):
        """
        현재 진행 중인 유닛 작업들의 완료 상태를 조회합니다.
        """
        try:
            user_no = self.user_no
            
            # 진행 중인 작업들 조회
            active_tasks = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.status == self.TASK_PROCESSING
            ).all()
            
            completion_info = []
            current_time = datetime.utcnow()
            
            for task in active_tasks:
                unit_redis = self.redis_manager.get_unit_manager()
                redis_completion_time = unit_redis.get_unit_completion_time(
                    user_no, task.unit_idx
                )
                
                if redis_completion_time:
                    remaining_seconds = max(0, int((redis_completion_time - current_time).total_seconds()))
                    completion_info.append({
                        "unit_idx": task.unit_idx,
                        "task_type": task.task_type,
                        "quantity": task.quantity,
                        "target_unit_idx": task.target_unit_idx,
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
            return {"success": False, "message": f"Error getting completion status: {str(e)}", "data": []}