from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
from datetime import datetime
import logging


class BuildingDBManager:
    """건물 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_model_class(self):
        return models.Building
    
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
            "building_idx": model_instance.building_idx,
            "building_lv": model_instance.building_lv,
            "status": model_instance.status,
            "start_time": model_instance.start_time.isoformat() if model_instance.start_time else None,
            "end_time": model_instance.end_time.isoformat() if model_instance.end_time else None,
            "last_dt": model_instance.last_dt.isoformat() if model_instance.last_dt else None,
        }
    
    def get_user_buildings(self, user_no: int, status: Optional[int] = None) -> Dict[str, Any]:
        """사용자의 모든 건물 조회"""
        try:
            query = self.db.query(models.Building).filter(
                models.Building.user_no == user_no
            )
            
            if status is not None:
                query = query.filter(models.Building.status == status)
            
            buildings = query.all()
            
            return self._format_response(
                True,
                f"Retrieved {len(buildings)} buildings",
                [self._serialize_model(building) for building in buildings]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user buildings: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting user buildings: {e}")
            return self._format_response(False, f"Error getting buildings: {str(e)}")
    
    def get_user_building(self, user_no: int, building_idx: int) -> Dict[str, Any]:
        """특정 건물 조회 - user_no로 권한 확인"""
        try:
            building = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            
            if not building:
                return self._format_response(False, "Building not found")
            
            return self._format_response(
                True,
                "Building retrieved successfully",
                self._serialize_model(building)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting building: {e}")
            return self._format_response(False, f"Error getting building: {str(e)}")
    
    def create_building(self, **kwargs) -> Dict[str, Any]:
        """건물 생성 - commit하지 않음"""
        try:
            new_building = models.Building(**kwargs)
            self.db.add(new_building)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Building created successfully",
                self._serialize_model(new_building)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating building: {e}")
            return self._format_response(False, f"Error creating building: {str(e)}")
    
    

    
    def update_building_status(self, user_no: int, building_idx: int, **update_fields) -> Dict[str, Any]:
        """건물 상태 업데이트 - user_no로 권한 확인"""
        try:
            # 먼저 해당 사용자의 건물인지 확인
            building = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            
            if not building:
                return self._format_response(False, "Building not found or no permission")
            
            # 업데이트 필드 적용
            for field, value in update_fields.items():
                if hasattr(building, field):
                    setattr(building, field, value)
            
            # 마지막 업데이트 시간 갱신
            building.last_dt = datetime.utcnow()
            
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Building updated successfully",
                self._serialize_model(building)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error updating building: {e}")
            return self._format_response(False, f"Error updating building: {str(e)}")
    
    def delete_building(self, user_no: int, building_idx: int) -> Dict[str, Any]:
        """건물 삭제 - user_no로 권한 확인"""
        try:
            building = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            
            if not building:
                return self._format_response(False, "Building not found or no permission")
            
            self.db.delete(building)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Building deleted successfully",
                {"user_no": user_no, "building_idx": building_idx}
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error deleting building: {e}")
            return self._format_response(False, f"Error deleting building: {str(e)}")
    
    def get_active_buildings(self, user_no: int) -> Dict[str, Any]:
        """진행 중인 건물들 조회"""
        try:
            buildings = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.status.in_([1, 2])  # 건설중, 업그레이드중
            ).all()
            
            return self._format_response(
                True,
                f"Retrieved {len(buildings)} active buildings",
                [self._serialize_model(building) for building in buildings]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting active buildings: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting active buildings: {e}")
            return self._format_response(False, f"Error getting active buildings: {str(e)}")