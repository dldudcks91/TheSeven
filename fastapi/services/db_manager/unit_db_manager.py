

# unit_db_manager.py
from .base_db_manager import BaseDBManager
from .db_types import TableType
import models
from typing import Any, Dict

class UnitDBManager(BaseDBManager):
    """유닛 전용 DB 관리자"""
    
    def __init__(self, db_session):
        super().__init__(db_session, TableType.UNIT)
    
    def get_model_class(self):
        return models.Unit
    
    def _get_primary_key(self) -> str:
        return "unit_idx"
    
    def validate_data(self, unit) -> bool:
        """유닛 데이터 유효성 검증"""
        if not hasattr(unit, 'user_no') or not unit.user_no:
            return False
        if not hasattr(unit, 'unit_type') or not unit.unit_type:
            return False
        return True
    
    def add_units(self, user_no: int, unit_type: int, count: int) -> Dict[str, Any]:
        """유닛 추가"""
        try:
            # 기존 유닛이 있는지 확인
            existing = self.db.query(models.Unit).filter(
                models.Unit.user_no == user_no,
                models.Unit.unit_type == unit_type
            ).first()
            
            if existing:
                # 기존 유닛 수량 증가
                return self.update(existing.unit_idx, count=existing.count + count)
            else:
                # 새 유닛 생성
                return self.create(
                    user_no=user_no,
                    unit_type=unit_type,
                    count=count
                )
                
        except Exception as e:
            return self._handle_db_error("add_units", e)