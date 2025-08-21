# UnitManager.py
from sqlalchemy.orm import Session
import models, schemas
from services import GameDataManager, ResourceManager
from datetime import datetime, timedelta

class UnitManager():
    CONFIG_TYPE = 'unit'
    
    # 작업 상태 상수
    TASK_PROCESSING = 1
    
    # 작업 타입 상수
    TASK_TRAIN = 0
    TASK_UPGRADE = 1
    
    def __init__(self, db: Session):
        self._user_no = None
        self._data = None
        self.db = db
        self.unit_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]    
        
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
            return {"success": False, "message": "Missing unit_idx", "data": {}}
        
        return None
    
    def _format_unit_data(self, unit):
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
            "upgrading": unit.upgrading
        }
    
    def _get_unit(self, user_no, unit_idx):
        return self.db.query(models.Unit).filter(
            models.Unit.user_no == user_no,
            models.Unit.unit_idx == unit_idx
        ).first()
    
    def _get_all_user_units(self, user_no):
        return self.db.query(models.Unit).filter(
            models.Unit.user_no == user_no
        ).all()
    
    def _handle_resource_transaction(self, user_no, unit_idx, quantity=1):
        try:
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][unit_idx]
            
            costs = required['cost']
            base_time = required['time']
            
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
    
    def _update_unit_counts(self, unit):
        calculated_total = unit.ready + unit.field + unit.injured + unit.wounded + unit.healing + unit.death + unit.training + unit.upgrading
        if unit.total != calculated_total:
            unit.total = calculated_total
    
    def _has_ongoing_task(self, user_no, unit_idx):
        """해당 유닛 타입에 진행중인 작업이 있는지 확인"""
        task = self.db.query(models.UnitTasks).filter(
            models.UnitTasks.user_no == user_no,
            models.UnitTasks.unit_idx == unit_idx,
            models.UnitTasks.status == self.TASK_PROCESSING
        ).first()
        return task is not None
    
    def _get_current_task(self, user_no, unit_idx):
        """현재 진행중인 작업 반환"""
        return self.db.query(models.UnitTasks).filter(
            models.UnitTasks.user_no == user_no,
            models.UnitTasks.unit_idx == unit_idx,
            models.UnitTasks.status == self.TASK_PROCESSING
        ).first()
    
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
                "data": {"units": units_data}
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}", "data": {}}
    
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
            quantity = self.data.get('quantity', 0)
                
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            if unit_idx not in self.unit_config:
                return {"success": False, "message": "Invalid unit type", "data": {}}
            
            # 진행중인 작업이 있는지 확인
            if self._has_ongoing_task(user_no, unit_idx):
                return {"success": False, "message": "Another task is already in progress for this unit type", "data": {}}
            
            unit = self._get_unit(user_no, unit_idx)
            if not unit:
                unit = models.Unit(
                    user_no=user_no,
                    unit_idx=unit_idx,
                    total=0, ready=0, field=0, injured=0, wounded=0, healing=0, death=0, training=0, upgrading=0,
                )
                self.db.add(unit)
                self.db.flush()
            
            config = self.unit_config[unit_idx]
            max_count = config.get('max_count', 999)
            if unit.total + quantity > max_count:
                return {"success": False, "message": f"Max {max_count} units allowed", "data": {}}
            
            base_time, error_msg = self._handle_resource_transaction(user_no, unit_idx, quantity)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 작업 시간 계산
            total_time = base_time * quantity
            current_time = datetime.utcnow()
            
            # 즉시 작업 시작
            task = models.UnitTasks(
                user_no=user_no,
                unit_idx=unit_idx,
                task_type=self.TASK_TRAIN,
                quantity=quantity,
                target_unit_idx=None,
                status=self.TASK_PROCESSING,
                start_time=current_time,
                end_time=current_time + timedelta(seconds=total_time),
                created_at=current_time
            )
            
            self.db.add(task)
            
            unit.training += quantity
            
            self.db.commit()
            self.db.refresh(unit)
            
            unit_name = config.get('name', f'Unit_{unit_idx}')
            return {
                "success": True,
                "message": f"Started production of {quantity} {unit_name} (Time: {total_time} seconds)",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error: {str(e)}", "data": {}}
    
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
            quantity = self.data.get('quantity', 1)
            
            if not target_unit_idx:
                return {"success": False, "message": "Missing target_unit_idx", "data": {}}
            
            # 진행중인 작업이 있는지 확인
            if self._has_ongoing_task(user_no, unit_idx):
                return {"success": False, "message": "Another task is already in progress for this unit type", "data": {}}
            
            unit = self._get_unit(user_no, unit_idx)
            if not unit:
                return {"success": False, "message": "Unit not found", "data": {}}
            
            if unit.ready < quantity:
                return {"success": False, "message": f"Not enough ready units. Available: {unit.ready}", "data": {}}
            
            base_time, error_msg = self._handle_resource_transaction(user_no, target_unit_idx, quantity)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 작업 시간 계산
            total_time = base_time * quantity
            current_time = datetime.utcnow()
            
            # 즉시 작업 시작
            task = models.UnitTasks(
                user_no=user_no,
                unit_idx=unit_idx,
                task_type=self.TASK_UPGRADE,
                quantity=quantity,
                target_unit_idx=target_unit_idx,
                status=self.TASK_PROCESSING,
                start_time=current_time,
                end_time=current_time + timedelta(seconds=total_time),
                created_at=current_time
            )
            
            self.db.add(task)
            
            unit.ready -= quantity
            unit.upgrading += quantity
            
            self.db.commit()
            self.db.refresh(unit)
            
            return {
                "success": True,
                "message": f"Started upgrade of {quantity} units (Time: {total_time} seconds)",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error: {str(e)}", "data": {}}
    
    def unit_finish(self):
        """
        유닛 훈련/업그레이드를 완료합니다.
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
            
            current_time = datetime.utcnow()
            
            task = self._get_current_task(user_no, unit_idx)
            if not task:
                return {"success": False, "message": "No task to complete", "data": {}}
            
            if task.end_time and current_time < task.end_time:
                remaining_time = int((task.end_time - current_time).total_seconds())
                return {"success": False, "message": f"Task not ready yet. {remaining_time} seconds remaining", "data": {}}
            
            if task.task_type == self.TASK_TRAIN:
                unit.total += task.quantity
                unit.ready += task.quantity
                unit.training -= task.quantity
                message = f"Completed production of {task.quantity} units"
                
            elif task.task_type == self.TASK_UPGRADE:
                unit.total -= task.quantity
                unit.upgrading -= task.quantity
                
                target_unit = self._get_unit(task.user_no, task.target_unit_idx)
                if not target_unit:
                    target_unit = models.Unit(
                        user_no=task.user_no,
                        unit_idx=task.target_unit_idx,
                        total=0, ready=0, field=0, injured=0, wounded=0, healing=0, death=0, training=0, upgrading=0,
                    )
                    self.db.add(target_unit)
                    self.db.flush()
                
                target_unit.total += task.quantity
                target_unit.ready += task.quantity
                
                message = f"Completed upgrade of {task.quantity} units"
            
            # 완료된 task 삭제
            self.db.delete(task)
            
            self._update_unit_counts(unit)
            
            self.db.commit()
            self.db.refresh(unit)
            
            return {
                "success": True,
                "message": message,
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error: {str(e)}", "data": {}}
    
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
                resource_manager.produce_resources(user_no, refund_costs)  # add_resources 대신 produce_resources 사용
                
            except Exception as refund_error:
                print(f"Refund failed: {refund_error}")
            
            # 취소된 task 삭제
            self.db.delete(task)
            
            self.db.commit()
            self.db.refresh(unit)
            
            return {
                "success": True,
                "message": f"Task cancelled, resources refunded",
                "data": self._format_unit_data(unit)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error: {str(e)}", "data": {}}
    
    def check_and_complete_tasks(self, user_no=None):
        """
        완료된 작업들을 자동으로 처리합니다.
        """
        try:
            current_time = datetime.utcnow()
            
            query = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.status == self.TASK_PROCESSING,
                models.UnitTasks.end_time <= current_time
            )
            
            if user_no:
                query = query.filter(models.UnitTasks.user_no == user_no)
            
            completed_tasks = query.all()
            results = []
            
            for task in completed_tasks:
                unit = self._get_unit(task.user_no, task.unit_idx)
                
                if task.task_type == self.TASK_TRAIN:
                    unit.total += task.quantity
                    unit.ready += task.quantity
                    unit.training -= task.quantity
                    
                elif task.task_type == self.TASK_UPGRADE:
                    unit.total -= task.quantity
                    unit.upgrading -= task.quantity
                    
                    target_unit = self._get_unit(task.user_no, task.target_unit_idx)
                    if not target_unit:
                        target_unit = models.Unit(
                            user_no=task.user_no,
                            unit_idx=task.target_unit_idx,
                            total=0, ready=0, field=0, injured=0, wounded=0, healing=0, death=0, training=0, upgrading=0,
                        )
                        self.db.add(target_unit)
                        self.db.flush()
                    
                    target_unit.total += task.quantity
                    target_unit.ready += task.quantity
                    
                # 완료된 task 삭제
                self.db.delete(task)
                
                self._update_unit_counts(unit)
                
                results.append({
                    "unit_idx": task.unit_idx,
                    "task_type": task.task_type,
                    "quantity": task.quantity
                })
            
            if results:
                self.db.commit()
            
            return {
                "success": True,
                "message": f"Completed {len(results)} tasks",
                "data": {"completed": results}
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error: {str(e)}", "data": {}}