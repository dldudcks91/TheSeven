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
        """응답 형태 통일"""
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def _serialize_model(self, model_instance) -> Dict[str, Any]:
        """모델 인스턴스를 딕셔너리로 변환"""
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
    
    def get_user_units(self, user_no: int) -> Dict[str, Any]:
        """사용자의 모든 유닛 조회"""
        try:
            units = self.db.query(models.Unit).filter(
                models.Unit.user_no == user_no
            ).all()
            
            return self._format_response(
                True,
                f"Retrieved {len(units)} units",
                [self._serialize_model(unit) for unit in units]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user units: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting user units: {e}")
            return self._format_response(False, f"Error getting units: {str(e)}")
    
    def get_unit(self, user_no: int, unit_idx: int):
        """특정 유닛 조회 - user_no로 권한 확인 (모델 인스턴스 반환)"""
        try:
            unit = self.db.query(models.Unit).filter(
                models.Unit.user_no == user_no,
                models.Unit.unit_idx == unit_idx
            ).first()
            
            return unit
        except Exception as e:
            self.logger.error(f"Error getting unit: {e}")
            return None
    
    def get_user_unit(self, user_no: int, unit_idx: int) -> Dict[str, Any]:
        """특정 유닛 조회 - user_no로 권한 확인 (딕셔너리 반환)"""
        try:
            unit = self.get_unit(user_no, unit_idx)
            
            if not unit:
                return self._format_response(False, "Unit not found")
            
            return self._format_response(
                True,
                "Unit retrieved successfully",
                self._serialize_model(unit)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting unit: {e}")
            return self._format_response(False, f"Error getting unit: {str(e)}")
    
    def get_all_user_units(self, user_no: int):
        """사용자의 모든 유닛 조회 (모델 인스턴스 리스트 반환)"""
        try:
            units = self.db.query(models.Unit).filter(
                models.Unit.user_no == user_no
            ).all()
            
            return units
        except Exception as e:
            self.logger.error(f"Error getting all user units: {e}")
            return []
    
    def create_unit(self, **kwargs) -> Dict[str, Any]:
        """유닛 생성 - commit하지 않음"""
        try:
            new_unit = models.Unit(**kwargs)
            self.db.add(new_unit)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Unit created successfully",
                self._serialize_model(new_unit)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating unit: {e}")
            return self._format_response(False, f"Error creating unit: {str(e)}")
    
    def update_unit(self, user_no: int, unit_idx: int, **update_fields) -> Dict[str, Any]:
        """유닛 상태 업데이트 - user_no로 권한 확인"""
        try:
            # 먼저 해당 사용자의 유닛인지 확인
            unit = self.get_unit(user_no, unit_idx)
            
            if not unit:
                return self._format_response(False, "Unit not found or no permission")
            
            # 업데이트 필드 적용
            for field, value in update_fields.items():
                if hasattr(unit, field):
                    setattr(unit, field, value)
            
            # total 자동 계산
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Unit updated successfully",
                self._serialize_model(unit)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error updating unit: {e}")
            return self._format_response(False, f"Error updating unit: {str(e)}")
    
    def delete_unit(self, user_no: int, unit_idx: int) -> Dict[str, Any]:
        """유닛 삭제 - user_no로 권한 확인"""
        try:
            unit = self.get_unit(user_no, unit_idx)
            
            if not unit:
                return self._format_response(False, "Unit not found or no permission")
            
            self.db.delete(unit)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Unit deleted successfully",
                {"user_no": user_no, "unit_idx": unit_idx}
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting unit: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error deleting unit: {e}")
            return self._format_response(False, f"Error deleting unit: {str(e)}")
    
    def get_current_task(self, user_no: int, unit_idx: int):
        """현재 진행중인 작업 반환 (모델 인스턴스)"""
        try:
            task = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.unit_idx == unit_idx,
                models.UnitTasks.status == 1  # TASK_PROCESSING
            ).first()
            
            return task
        except Exception as e:
            self.logger.error(f"Error getting current task: {e}")
            return None
    
    def has_ongoing_task(self, user_no: int, unit_idxs: List[int]) -> bool:
        """해당 유닛 타입에 진행중인 작업이 있는지 확인"""
        try:
            if not isinstance(unit_idxs, list):
                unit_idxs = [unit_idxs]
            
            task = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.unit_idx.in_(unit_idxs),
                models.UnitTasks.status == 1  # TASK_PROCESSING
            ).first()
            
            return task is not None
        except Exception as e:
            self.logger.error(f"Error checking ongoing task: {e}")
            return False
    
    def get_active_tasks(self, user_no: int) -> List[Dict[str, Any]]:
        """진행 중인 작업들 조회"""
        try:
            tasks = self.db.query(models.UnitTasks).filter(
                models.UnitTasks.user_no == user_no,
                models.UnitTasks.status == 1  # TASK_PROCESSING
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
        """유닛 훈련 시작 - DB 업데이트"""
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            
            # 작업 생성
            task = models.UnitTasks(
                user_no=user_no,
                unit_idx=unit_idx,
                task_type=0,  # TASK_TRAIN
                quantity=quantity,
                target_unit_idx=None,
                status=1,  # TASK_PROCESSING
                start_time=start_time,
                end_time=None,
                created_at=start_time
            )
            
            self.db.add(task)
            unit.training += quantity
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            
            self.db.flush()
            
            return self._format_response(
                True,
                "Unit training started",
                unit
            )
        except Exception as e:
            self.logger.error(f"Error starting unit train: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def start_unit_upgrade(self, user_no: int, unit_idx: int, quantity: int, 
                          target_unit_idx: int, start_time: datetime) -> Dict[str, Any]:
        """유닛 업그레이드 시작 - DB 업데이트"""
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            
            # 작업 생성
            task = models.UnitTasks(
                user_no=user_no,
                unit_idx=unit_idx,
                task_type=1,  # TASK_UPGRADE
                quantity=quantity,
                target_unit_idx=target_unit_idx,
                status=1,  # TASK_PROCESSING
                start_time=start_time,
                end_time=None,
                created_at=start_time
            )
            
            self.db.add(task)
            unit.ready -= quantity
            unit.upgrading += quantity
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            
            self.db.flush()
            
            return self._format_response(
                True,
                "Unit upgrade started",
                unit
            )
        except Exception as e:
            self.logger.error(f"Error starting unit upgrade: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def cancel_unit_task(self, user_no: int, unit_idx: int, task) -> Dict[str, Any]:
        """유닛 작업 취소 - DB 업데이트"""
        try:
            unit = self.get_unit(user_no, unit_idx)
            if not unit:
                return self._format_response(False, "Unit not found")
            
            # 작업 타입에 따라 유닛 상태 복원
            if task.task_type == 1:  # TASK_UPGRADE
                unit.ready += task.quantity
                unit.upgrading -= task.quantity
            else:  # TASK_TRAIN
                unit.training -= task.quantity
            
            # 작업 삭제
            self.db.delete(task)
            
            # total 재계산
            unit.total = (unit.ready + unit.field + unit.injured + 
                         unit.wounded + unit.healing + unit.death + 
                         unit.training + unit.upgrading)
            
            self.db.flush()
            
            return self._format_response(
                True,
                "Unit task cancelled",
                unit
            )
        except Exception as e:
            self.logger.error(f"Error cancelling unit task: {e}")
            return self._format_response(False, f"Error: {str(e)}")