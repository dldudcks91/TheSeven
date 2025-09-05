



# buff_db_manager.py
from .base_db_manager import BaseDBManager
from .db_types import TableType
import models

class BuffDBManager(BaseDBManager):
    """버프 전용 DB 관리자"""
    
    def __init__(self, db_session):
        super().__init__(db_session, TableType.BUFF)
    
    def get_model_class(self):
        return models.Buff
    
    def _get_primary_key(self) -> str:
        return "buff_idx"
    
    def validate_data(self, buff) -> bool:
        """버프 데이터 유효성 검증"""
        if not hasattr(buff, 'user_no') or not buff.user_no:
            return False
        return True

