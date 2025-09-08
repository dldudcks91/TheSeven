# 1. BuildingDBManager - 순수 DB 작업만 담당
from typing import Optional, List, Dict, Any
from .base_db_manager import BaseDBManager
from .db_types import TableType
import models
from datetime import datetime

class BuildingDBManager(BaseDBManager):
    """건물 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""
    
    def __init__(self, db_session):
        super().__init__(db_session, TableType.BUILDING)
    
    def get_model_class(self):
        return models.Building
    
    def _get_primary_key(self) -> str:
        return "building_idx"
    
    def validate_data(self, building) -> bool:
        """건물 데이터 유효성 검증"""
        if isinstance(building, dict):
            return building.get('user_no') and building.get('building_idx')
        else:
            return (hasattr(building, 'user_no') and building.user_no and 
                   hasattr(building, 'building_idx') and building.building_idx)
    
    def create_building(self, **kwargs) -> Dict[str, Any]:
        """건물 생성"""
        return self.create(**kwargs)
    
    
    
    def get_user_buildings(self, user_no: int, status: Optional[int] = None) -> Dict[str, Any]:
        """사용자의 모든 건물 조회"""
        filters = {}
        if status is not None:
            filters['status'] = status
        return self.get_by_user(user_no, **filters)
    
    def get_building_by_idx(self, user_no: int, building_idx: int) -> Dict[str, Any]:
        """특정 건물 조회"""
        try:
            model_class = self.get_model_class()
            record = self.db.query(model_class).filter(
                model_class.user_no == user_no,
                model_class.building_idx == building_idx
            ).first()
            
            if not record:
                return self._format_response(False, "Building not found")
            
            return self._format_response(
                True,
                "Building retrieved successfully",
                self._serialize_model(record)
            )
        except Exception as e:
            return self._handle_db_error("get_building_by_idx", e)
    
    def update_building_status(self, building_idx: int, status: int) -> Dict[str, Any]:
        """건물 상태 업데이트"""
        return self.update(building_idx, status=status)
    
    def complete_building(self, building_idx: int) -> Dict[str, Any]:
        """건물 완료 처리"""
        return self.update(
            building_idx,
            status=3,  # 완료 상태
            end_time=datetime.utcnow()
        )
    
    def get_active_buildings(self, user_no: int) -> Dict[str, Any]:
        """진행 중인 건물들 조회"""
        try:
            model_class = self.get_model_class()
            records = self.db.query(model_class).filter(
                model_class.user_no == user_no,
                model_class.status.in_([1, 2])
            ).all()
            
            return self._format_response(
                True,
                f"Retrieved {len(records)} active buildings",
                [self._serialize_model(record) for record in records]
            )
        except Exception as e:
            return self._handle_db_error("get_active_buildings", e)