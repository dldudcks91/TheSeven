# research_db_manager.py  
from .base_db_manager import BaseDBManager
from .db_types import TableType
import models

class ResearchDBManager(BaseDBManager):
    """연구 전용 DB 관리자"""
    
    def __init__(self, db_session):
        super().__init__(db_session, TableType.RESEARCH)
    
    def get_model_class(self):
        return models.Research
    
    def _get_primary_key(self) -> str:
        return "research_idx"
    
    def validate_data(self, research) -> bool:
        """연구 데이터 유효성 검증"""
        if not hasattr(research, 'user_no') or not research.user_no:
            return False
        if not hasattr(research, 'research_type') or not research.research_type:
            return False
        return True