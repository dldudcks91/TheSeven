from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
from datetime import datetime
import logging


class ResearchDBManager:
    """연구 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_model_class(self):
        return models.Research
    
    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def _serialize_model(self, model_instance) -> Dict[str, Any]:
        return {
            "user_no": model_instance.user_no,
            "research_idx": model_instance.research_idx,
            "research_lv": model_instance.research_lv,
            "status": model_instance.status,
            "start_time": model_instance.start_time.isoformat() if model_instance.start_time else None,
            "end_time": model_instance.end_time.isoformat() if model_instance.end_time else None,
            "last_dt": model_instance.last_dt.isoformat() if model_instance.last_dt else None,
        }
    
    # ============================================
    # 동기화용 bulk upsert
    # ============================================
    
    def bulk_upsert_researches(self, user_no: int, researches_data: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Redis 연구 데이터를 MySQL에 bulk upsert
        
        Args:
            user_no: 유저 번호
            researches_data: {research_idx: {id, user_no, research_idx, research_lv, status, ...}}
        """
        try:
            existing = self.db.query(models.Research).filter(
                models.Research.user_no == user_no
            ).all()
            existing_map = {str(r.research_idx): r for r in existing}
            
            for research_idx_str, data in researches_data.items():
                research_idx = int(research_idx_str)
                
                if research_idx_str in existing_map:
                    r = existing_map[research_idx_str]
                    r.research_lv = data.get('research_lv', r.research_lv)
                    r.status = data.get('status', r.status)
                    r.start_time = self._parse_datetime(data.get('start_time'))
                    r.end_time = self._parse_datetime(data.get('end_time'))
                    r.last_dt = self._parse_datetime(data.get('last_dt')) or datetime.utcnow()
                else:
                    new_research = models.Research(
                        user_no=user_no,
                        research_idx=research_idx,
                        research_lv=data.get('research_lv', 0),
                        status=data.get('status', 0),
                        start_time=self._parse_datetime(data.get('start_time')),
                        end_time=self._parse_datetime(data.get('end_time')),
                        last_dt=self._parse_datetime(data.get('last_dt')) or datetime.utcnow()
                    )
                    self.db.add(new_research)
            
            self.db.flush()
            
            return self._format_response(True, f"Synced {len(researches_data)} researches for user {user_no}")
            
        except SQLAlchemyError as e:
            self.logger.error(f"bulk_upsert_researches error: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def _parse_datetime(self, value) -> Optional[datetime]:
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
    
    def get_user_researches(self, user_no: int, status: Optional[int] = None) -> Dict[str, Any]:
        try:
            query = self.db.query(models.Research).filter(models.Research.user_no == user_no)
            if status is not None:
                query = query.filter(models.Research.status == status)
            researchs = query.all()
            return self._format_response(True, f"Retrieved {len(researchs)} researchs", [self._serialize_model(r) for r in researchs])
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user researchs: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def get_user_research(self, user_no: int, research_idx: int) -> Dict[str, Any]:
        try:
            research = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.research_idx == research_idx
            ).first()
            if not research:
                return self._format_response(False, "Research not found")
            return self._format_response(True, "Research retrieved successfully", self._serialize_model(research))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def create_research(self, **kwargs) -> Dict[str, Any]:
        try:
            new_research = models.Research(**kwargs)
            self.db.add(new_research)
            self.db.flush()
            return self._format_response(True, "Research created successfully", self._serialize_model(new_research))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def update_research_status(self, user_no: int, research_idx: int, **update_fields) -> Dict[str, Any]:
        try:
            research = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.research_idx == research_idx
            ).first()
            if not research:
                return self._format_response(False, "Research not found or no permission")
            for field, value in update_fields.items():
                if hasattr(research, field):
                    setattr(research, field, value)
            research.last_dt = datetime.utcnow()
            self.db.flush()
            return self._format_response(True, "Research updated successfully", self._serialize_model(research))
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def delete_research(self, user_no: int, research_idx: int) -> Dict[str, Any]:
        try:
            research = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.research_idx == research_idx
            ).first()
            if not research:
                return self._format_response(False, "Research not found or no permission")
            self.db.delete(research)
            self.db.flush()
            return self._format_response(True, "Research deleted successfully", {"user_no": user_no, "research_idx": research_idx})
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
    
    def get_active_researchs(self, user_no: int) -> Dict[str, Any]:
        try:
            researchs = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.status.in_([1, 2])
            ).all()
            return self._format_response(True, f"Retrieved {len(researchs)} active researchs", [self._serialize_model(r) for r in researchs])
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting active researchs: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
