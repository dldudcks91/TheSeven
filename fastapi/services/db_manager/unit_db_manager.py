from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
from datetime import datetime
import logging


class UnitDBManager:
    """유닛 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_model_class(self):
        return models.Unit
    
    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def _serialize_model(self, model_instance) -> Dict[str, Any]:
        return {
            "id": model_instance.id,
            "user_no": model_instance.user_no,
            "unit_idx": model_instance.unit_idx,
            "total": model_instance.total,
            "ready": model_instance.ready,
            "field": model_instance.field,
            "injured": model_instance.injured,
            "wounded": model_instance.wounded,
            "healing": model_instance.healing,
            "death": model_instance.death,
            "training": model_instance.training,
            "upgrading": model_instance.upgrading,
        }
    
    # ============================================
    # 동기화용 bulk upsert
    # ============================================
    
    def bulk_upsert_units(self, user_no: int, units_data: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Redis 유닛 데이터를 MySQL에 bulk upsert
        
        Args:
            user_no: 유저 번호
            units_data: {unit_idx: {id, user_no, unit_idx, total, ready, field, ...}}
        """
        try:
            existing = self.db.query(models.Unit).filter(
                models.Unit.user_no == user_no
            ).all()
            existing_map = {str(u.unit_idx): u for u in existing}
            
            for unit_idx_str, data in units_data.items():
                unit_idx = int(unit_idx_str)
                
                if unit_idx_str in existing_map:
                    u = existing_map[unit_idx_str]
                    u.total = data.get('total', u.total)
                    u.ready = data.get('ready', u.ready)
                    u.field = data.get('field', u.field)
                    u.injured = data.get('injured', u.injured)
                    u.wounded = data.get('wounded', u.wounded)
                    u.healing = data.get('healing', u.healing)
                    u.death = data.get('death', u.death)
                    u.training = data.get('training', u.training)
                    u.upgrading = data.get('upgrading', u.upgrading)
                else:
                    new_unit = models.Unit(
                        user_no=user_no,
                        unit_idx=unit_idx,
                        total=data.get('total', 0),
                        ready=data.get('ready', 0),
                        field=data.get('field', 0),
                        injured=data.get('injured', 0),
                        wounded=data.get('wounded', 0),
                        healing=data.get('healing', 0),
                        death=data.get('death', 0),
                        training=data.get('training', 0),
                        upgrading=data.get('upgrading', 0)
                    )
                    self.db.add(new_unit)
            
            self.db.flush()
            
            return self._format_response(True, f"Synced {len(units_data)} units for user {user_no}")
            
        except SQLAlchemyError as e:
            self.logger.error(f"bulk_upsert_units error: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    # ============================================
    # 기존 메서드들 (변경 없음)
    # ============================================
    
    def get_user_units(self, user_no: int) -> Dict[str, Any]:
        try:
            units = self.db.query(models.Unit).filter(models.Unit.user_no == user_no).all()
            return self._format_response(True, f"Retrieved {len(units)} units", [self._serialize_model(u) for u in units])
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user units: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def get_unit(self, user_no: int, unit_idx: int):
        try:
            return self.db.query(models.Unit).filter(
                models.Unit.user_no == user_no,
                models.Unit.unit_idx == unit_idx
            ).first()
        except Exception as e:
            self.logger.error(f"Error getting unit: {e}")
            return None
    
    def get_user_unit(self, user_no: int, unit_idx: int) -> Dict[str, Any]:
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            return self._format_response(True, "Unit retrieved successfully", self._serialize_model(unit))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def get_all_user_units(self, user_no: int):
        try:
            return self.db.query(models.Unit).filter(models.Unit.user_no == user_no).all()
        except Exception as e:
            self.logger.error(f"Error getting all user units: {e}")
            return []
    
    def create_unit(self, **kwargs) -> Dict[str, Any]:
        try:
            new_unit = models.Unit(**kwargs)
            self.db.add(new_unit)
            self.db.flush()
            return self._format_response(True, "Unit created successfully", self._serialize_model(new_unit))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def update_unit(self, user_no: int, unit_idx: int, **update_fields) -> Dict[str, Any]:
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found or no permission")
            for field, value in update_fields.items():
                if hasattr(unit, field):
                    setattr(unit, field, value)
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            self.db.flush()
            return self._format_response(True, "Unit updated successfully", self._serialize_model(unit))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def delete_unit(self, user_no: int, unit_idx: int) -> Dict[str, Any]:
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found or no permission")
            self.db.delete(unit)
            self.db.flush()
            return self._format_response(True, "Unit deleted successfully", {"user_no": user_no, "unit_idx": unit_idx})
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def get_current_task(self, user_no: int, unit_idx: int):
        try:
            return self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.unit_idx == unit_idx,
                models.UnitTasks.status == 1
            ).first()
        except Exception as e:
            self.logger.error(f"Error getting current task: {e}")
            return None
    
    def has_ongoing_task(self, user_no: int, unit_idxs: List[int]) -> bool:
        try:
            if not isinstance(unit_idxs, list):
                unit_idxs = [unit_idxs]
            task = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.unit_idx.in_(unit_idxs),
                models.UnitTasks.status == 1
            ).first()
            return task is not None
        except Exception as e:
            self.logger.error(f"Error checking ongoing task: {e}")
            return False
    
    def get_active_tasks(self, user_no: int) -> List[Dict[str, Any]]:
        try:
            tasks = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.status == 1
            ).all()
            result = []
            for task in tasks:
                result.append({
                    "unit_idx": task.unit_idx,
                    "task_type": task.task_type,
                    "quantity": task.quantity,
                    "target_unit_idx": task.target_unit_idx,
                    "start_time": task.start_time.isoformat() if task.start_time else None
                })
            return result
        except Exception as e:
            self.logger.error(f"Error getting active tasks: {e}")
            return []
    
    def start_unit_train(self, user_no: int, unit_idx: int, quantity: int, start_time: datetime) -> Dict[str, Any]:
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            task = models.UnitTasks(
                user_no=user_no, unit_idx=unit_idx, task_type=0,
                quantity=quantity, target_unit_idx=None, status=1,
                start_time=start_time, end_time=None, created_at=start_time
            )
            self.db.add(task)
            unit.training += quantity
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            self.db.flush()
            return self._format_response(True, "Unit training started", unit)
        except Exception as e:
            self.logger.error(f"Error starting unit train: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def start_unit_upgrade(self, user_no: int, unit_idx: int, quantity: int, 
                          target_unit_idx: int, start_time: datetime) -> Dict[str, Any]:
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            task = models.UnitTasks(
                user_no=user_no, unit_idx=unit_idx, task_type=1,
                quantity=quantity, target_unit_idx=target_unit_idx, status=1,
                start_time=start_time, end_time=None, created_at=start_time
            )
            self.db.add(task)
            unit.ready -= quantity
            unit.upgrading += quantity
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            self.db.flush()
            return self._format_response(True, "Unit upgrade started", unit)
        except Exception as e:
            self.logger.error(f"Error starting unit upgrade: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def cancel_unit_task(self, user_no: int, unit_idx: int, task) -> Dict[str, Any]:
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            if task.task_type == 1:
                unit.ready += task.quantity
                unit.upgrading -= task.quantity
            else:
                unit.training -= task.quantity
            self.db.delete(task)
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            self.db.flush()
            return self._format_response(True, "Unit task cancelled", unit)
        except Exception as e:
            self.logger.error(f"Error cancelling unit task: {e}")
            return self._format_response(False, f"Error: {str(e)}")
