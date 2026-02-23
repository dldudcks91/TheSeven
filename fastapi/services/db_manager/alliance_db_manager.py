from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Alliance, AllianceMember, AllianceApplication, AllianceResearch
from datetime import datetime
import logging
from typing import Dict, Any, Optional


class AllianceDBManager:
    """
    연맹 DB 관리자 - SyncWorker에서 사용
    
    Redis → MySQL 동기화 시 upsert(INSERT ON DUPLICATE KEY UPDATE) 패턴 사용
    """
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    # ==================== 연맹 기본 정보 ====================
    
    def upsert_alliance(self, alliance_id: int, info: Dict[str, Any]) -> Dict:
        """연맹 기본 정보 upsert"""
        try:
            alliance = self.db_session.query(Alliance).filter(
                Alliance.alliance_id == alliance_id
            ).first()
            
            if alliance:
                alliance.name = info.get('name', alliance.name)
                alliance.level = info.get('level', alliance.level)
                alliance.exp = info.get('exp', alliance.exp)
                alliance.leader_no = info.get('leader_no', alliance.leader_no)
                alliance.join_type = info.get('join_type', alliance.join_type)
                alliance.notice = info.get('notice')
                alliance.notice_updated_at = self._parse_datetime(info.get('notice_updated_at'))
                alliance.updated_at = datetime.utcnow()
            else:
                alliance = Alliance(
                    alliance_id=alliance_id,
                    name=info.get('name', ''),
                    level=info.get('level', 1),
                    exp=info.get('exp', 0),
                    leader_no=info.get('leader_no', 0),
                    join_type=info.get('join_type', 'free'),
                    notice=info.get('notice'),
                    notice_updated_at=self._parse_datetime(info.get('notice_updated_at')),
                    created_at=self._parse_datetime(info.get('created_at')) or datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                self.db_session.add(alliance)
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error upserting alliance {alliance_id}: {e}")
            return {"success": False, "message": str(e)}
    
    def delete_alliance(self, alliance_id: int):
        """연맹 삭제"""
        try:
            self.db_session.query(Alliance).filter(
                Alliance.alliance_id == alliance_id
            ).delete()
        except Exception as e:
            self.logger.error(f"Error deleting alliance {alliance_id}: {e}")
    
    # ==================== 멤버 ====================
    
    def upsert_member(self, alliance_id: int, user_no: int, member_data: Dict[str, Any]) -> Dict:
        """멤버 upsert"""
        try:
            member = self.db_session.query(AllianceMember).filter(
                AllianceMember.alliance_id == alliance_id,
                AllianceMember.user_no == user_no
            ).first()
            
            if member:
                member.position = member_data.get('position', member.position)
                member.donated_exp = member_data.get('donated_exp', member.donated_exp)
                member.donated_coin = member_data.get('donated_coin', member.donated_coin)
            else:
                member = AllianceMember(
                    alliance_id=alliance_id,
                    user_no=user_no,
                    position=member_data.get('position', 4),
                    donated_exp=member_data.get('donated_exp', 0),
                    donated_coin=member_data.get('donated_coin', 0),
                    joined_at=self._parse_datetime(member_data.get('joined_at')) or datetime.utcnow()
                )
                self.db_session.add(member)
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error upserting member {user_no} in alliance {alliance_id}: {e}")
            return {"success": False, "message": str(e)}
    
    def delete_all_members(self, alliance_id: int):
        """연맹의 모든 멤버 삭제"""
        try:
            self.db_session.query(AllianceMember).filter(
                AllianceMember.alliance_id == alliance_id
            ).delete()
        except Exception as e:
            self.logger.error(f"Error deleting all members for alliance {alliance_id}: {e}")
    
    # ==================== 가입 신청 ====================
    
    def upsert_application(self, alliance_id: int, user_no: int, app_data: Dict[str, Any]) -> Dict:
        """가입 신청 upsert"""
        try:
            application = self.db_session.query(AllianceApplication).filter(
                AllianceApplication.alliance_id == alliance_id,
                AllianceApplication.user_no == user_no
            ).first()
            
            if not application:
                application = AllianceApplication(
                    alliance_id=alliance_id,
                    user_no=user_no,
                    applied_at=self._parse_datetime(app_data.get('applied_at')) or datetime.utcnow()
                )
                self.db_session.add(application)
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error upserting application {user_no} in alliance {alliance_id}: {e}")
            return {"success": False, "message": str(e)}
    
    def delete_all_applications(self, alliance_id: int):
        """연맹의 모든 가입 신청 삭제"""
        try:
            self.db_session.query(AllianceApplication).filter(
                AllianceApplication.alliance_id == alliance_id
            ).delete()
        except Exception as e:
            self.logger.error(f"Error deleting all applications for alliance {alliance_id}: {e}")
    
    # ==================== 연구 ====================
    
    def upsert_research(self, alliance_id: int, research_idx: int, research_data: Dict[str, Any]) -> Dict:
        """연구 upsert"""
        try:
            research = self.db_session.query(AllianceResearch).filter(
                AllianceResearch.alliance_id == alliance_id,
                AllianceResearch.research_idx == research_idx
            ).first()
            
            if research:
                research.level = research_data.get('level', research.level)
                research.current_exp = research_data.get('current_exp', research.current_exp)
                research.is_active = 1 if research_data.get('is_active') == 1 else 0
                research.activated_by = research_data.get('activated_by')
                research.activated_at = self._parse_datetime(research_data.get('activated_at'))
                research.completed_at = self._parse_datetime(research_data.get('completed_at'))
            else:
                research = AllianceResearch(
                    alliance_id=alliance_id,
                    research_idx=research_idx,
                    level=research_data.get('level', 0),
                    current_exp=research_data.get('current_exp', 0),
                    is_active=1 if research_data.get('is_active') == 1 else 0,
                    activated_by=research_data.get('activated_by'),
                    activated_at=self._parse_datetime(research_data.get('activated_at')),
                    completed_at=self._parse_datetime(research_data.get('completed_at'))
                )
                self.db_session.add(research)
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error upserting research {research_idx} in alliance {alliance_id}: {e}")
            return {"success": False, "message": str(e)}
    
    def delete_all_research(self, alliance_id: int):
        """연맹의 모든 연구 삭제"""
        try:
            self.db_session.query(AllianceResearch).filter(
                AllianceResearch.alliance_id == alliance_id
            ).delete()
        except Exception as e:
            self.logger.error(f"Error deleting all research for alliance {alliance_id}: {e}")
    
    # ==================== 유틸리티 ====================
    
    def _parse_datetime(self, value) -> Optional[datetime]:
        """ISO 문자열을 datetime으로 변환"""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None