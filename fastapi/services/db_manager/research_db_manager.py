from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
from datetime import datetime
import logging


class ResearchDBManager:
    """연구 전용 DB 관리자 - 순수 데이터 조회/저장만 담당 (BuildingDBManager 미러링)"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_model_class(self):
        # 모델 클래스를 Research로 변경
        return models.Research
    
    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        """응답 형태 통일"""
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def _serialize_model(self, model_instance) -> Dict[str, Any]:
        """모델 인스턴스를 딕셔너리로 변환 (연구 필드에 맞게 수정)"""
        return {
            "id": model_instance.id,
            "user_no": model_instance.user_no,
            "research_idx": model_instance.research_idx, # building_idx -> research_idx
            "research_lv": model_instance.research_lv,   # building_lv -> research_lv
            "status": model_instance.status,
            "start_time": model_instance.start_time.isoformat() if model_instance.start_time else None,
            "end_time": model_instance.end_time.isoformat() if model_instance.end_time else None,
            "last_dt": model_instance.last_dt.isoformat() if model_instance.last_dt else None,
        }
    
    def get_user_researches(self, user_no: int, status: Optional[int] = None) -> Dict[str, Any]:
        """사용자의 모든 연구 조회 (get_user_buildings 미러링)"""
        try:
            # 모델 클래스를 Research로 변경
            query = self.db.query(models.Research).filter(
                models.Research.user_no == user_no
            )
            
            if status is not None:
                query = query.filter(models.Research.status == status)
            
            researchs = query.all()
            
            return self._format_response(
                True,
                f"Retrieved {len(researchs)} researchs",
                [self._serialize_model(research) for research in researchs]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user researchs: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting user researchs: {e}")
            return self._format_response(False, f"Error getting researchs: {str(e)}")
    
    def get_user_research(self, user_no: int, research_idx: int) -> Dict[str, Any]:
        """특정 연구 조회 - user_no로 권한 확인 (get_user_building 미러링)"""
        try:
            # 모델 클래스와 필드를 Research에 맞게 변경
            research = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.research_idx == research_idx
            ).first()
            
            if not research:
                return self._format_response(False, "Research not found")
            
            return self._format_response(
                True,
                "Research retrieved successfully",
                self._serialize_model(research)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting research: {e}")
            return self._format_response(False, f"Error getting research: {str(e)}")
    
    def create_research(self, **kwargs) -> Dict[str, Any]:
        """연구 생성 - commit하지 않음 (create_building 미러링)"""
        try:
            # 모델 클래스를 Research로 변경
            new_research = models.Research(**kwargs)
            self.db.add(new_research)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Research created successfully",
                self._serialize_model(new_research)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating research: {e}")
            return self._format_response(False, f"Error creating research: {str(e)}")
    
    def update_research_status(self, user_no: int, research_idx: int, **update_fields) -> Dict[str, Any]:
        """연구 상태 업데이트 - user_no로 권한 확인 (update_building_status 미러링)"""
        try:
            # 모델 클래스와 필드를 Research에 맞게 변경
            research = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.research_idx == research_idx
            ).first()
            
            if not research:
                return self._format_response(False, "Research not found or no permission")
            
            # 업데이트 필드 적용
            for field, value in update_fields.items():
                if hasattr(research, field):
                    setattr(research, field, value)
            
            # 마지막 업데이트 시간 갱신
            research.last_dt = datetime.utcnow()
            
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Research updated successfully",
                self._serialize_model(research)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error updating research: {e}")
            return self._format_response(False, f"Error updating research: {str(e)}")
    
    def delete_research(self, user_no: int, research_idx: int) -> Dict[str, Any]:
        """연구 삭제 - user_no로 권한 확인 (delete_building 미러링)"""
        try:
            # 모델 클래스와 필드를 Research에 맞게 변경
            research = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.research_idx == research_idx
            ).first()
            
            if not research:
                return self._format_response(False, "Research not found or no permission")
            
            self.db.delete(research)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Research deleted successfully",
                {"user_no": user_no, "research_idx": research_idx}
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting research: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error deleting research: {e}")
            return self._format_response(False, f"Error deleting research: {str(e)}")
    
    def get_active_researchs(self, user_no: int) -> Dict[str, Any]:
        """진행 중인 연구들 조회 (get_active_buildings 미러링)"""
        try:
            # 모델 클래스를 Research로 변경
            researchs = self.db.query(models.Research).filter(
                models.Research.user_no == user_no,
                models.Research.status.in_([1, 2])  # 연구중 (1) 또는 연구 완료 대기중 (2 등, 상태는 DB 정의에 따라 조정 필요)
            ).all()
            
            return self._format_response(
                True,
                f"Retrieved {len(researchs)} active researchs",
                [self._serialize_model(research) for research in researchs]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting active researchs: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting active researchs: {e}")
            return self._format_response(False, f"Error getting active researchs: {str(e)}")