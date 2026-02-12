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
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def _serialize_model(self, model_instance) -> Dict[str, Any]:
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
    
    # ============================================
    # 동기화용 bulk upsert
    # ============================================
    
    def bulk_upsert_buildings(self, user_no: int, buildings_data: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Redis 건물 데이터를 MySQL에 bulk upsert
        
        Args:
            user_no: 유저 번호
            buildings_data: {building_idx: {building_idx, building_lv, status, start_time, end_time, last_dt, ...}}
        """
        try:
            # 기존 건물 조회 (user_no 기준)
            existing = self.db.query(models.Building).filter(
                models.Building.user_no == user_no
            ).all()
            existing_map = {str(b.building_idx): b for b in existing}
            
            for building_idx_str, data in buildings_data.items():
                building_idx = int(building_idx_str)
                
                if building_idx_str in existing_map:
                    # UPDATE
                    b = existing_map[building_idx_str]
                    b.building_lv = data.get('building_lv') or b.building_lv
                    b.status = data.get('status', b.status)
                    b.start_time = self._parse_datetime(data.get('start_time'))
                    b.end_time = self._parse_datetime(data.get('end_time'))
                    b.last_dt = self._parse_datetime(data.get('last_dt')) or datetime.utcnow()
                else:
                    # INSERT
                    new_building = models.Building(
                        user_no=user_no,
                        building_idx=building_idx,
                        building_lv=data.get('building_lv') or 0,
                        status=data.get('status', 0),
                        start_time=self._parse_datetime(data.get('start_time')),
                        end_time=self._parse_datetime(data.get('end_time')),
                        last_dt=self._parse_datetime(data.get('last_dt')) or datetime.utcnow()
                    )
                    self.db.add(new_building)
            
            self.db.flush()
            
            return self._format_response(True, f"Synced {len(buildings_data)} buildings for user {user_no}")
            
        except SQLAlchemyError as e:
            self.logger.error(f"bulk_upsert_buildings error: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def _parse_datetime(self, value) -> Optional[datetime]:
        """문자열 또는 datetime을 datetime으로 변환"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
    
    # ============================================
    # 기존 메서드들 (변경 없음)
    # ============================================
    
    def get_user_buildings(self, user_no: int, status: Optional[int] = None) -> Dict[str, Any]:
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
    
    def get_user_building(self, user_no: int, building_idx: int) -> Dict[str, Any]:
        try:
            building = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            if not building:
                return self._format_response(False, "Building not found")
            return self._format_response(True, "Building retrieved successfully", self._serialize_model(building))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def create_building(self, **kwargs) -> Dict[str, Any]:
        try:
            new_building = models.Building(**kwargs)
            self.db.add(new_building)
            self.db.flush()
            return self._format_response(True, "Building created successfully", self._serialize_model(new_building))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def update_building_status(self, user_no: int, building_idx: int, **update_fields) -> Dict[str, Any]:
        try:
            building = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            if not building:
                return self._format_response(False, "Building not found or no permission")
            for field, value in update_fields.items():
                if hasattr(building, field):
                    setattr(building, field, value)
            building.last_dt = datetime.utcnow()
            self.db.flush()
            return self._format_response(True, "Building updated successfully", self._serialize_model(building))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def delete_building(self, user_no: int, building_idx: int) -> Dict[str, Any]:
        try:
            building = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            if not building:
                return self._format_response(False, "Building not found or no permission")
            self.db.delete(building)
            self.db.flush()
            return self._format_response(True, "Building deleted successfully", {"user_no": user_no, "building_idx": building_idx})
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def get_active_buildings(self, user_no: int) -> Dict[str, Any]:
        try:
            buildings = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.status.in_([1, 2])
            ).all()
            return self._format_response(
                True,
                f"Retrieved {len(buildings)} active buildings",
                [self._serialize_model(building) for building in buildings]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting active buildings: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
