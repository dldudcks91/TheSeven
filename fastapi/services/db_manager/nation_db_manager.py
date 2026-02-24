from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
from datetime import datetime
import logging


class NationDBManager:
    """유저 국가 정보 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)

    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }

    def _serialize_model(self, nation, alliance_member=None) -> Dict[str, Any]:
        return {
            "user_no": nation.user_no,
            "account_no": nation.account_no,
            "name": nation.name,
            "hq_lv": nation.hq_lv,
            "power": nation.power,
            "alliance_no": alliance_member.alliance_no if alliance_member else nation.alliance_no,
            "alliance_position": alliance_member.position if alliance_member else None,
            "cr_dt": nation.cr_dt.isoformat() if nation.cr_dt else None,
            "last_dt": nation.last_dt.isoformat() if nation.last_dt else None,
        }

    # ============================================
    # 조회
    # ============================================

    def get_user_nation(self, user_no: int) -> Dict[str, Any]:
        """유저 국가 정보 조회 (alliance_member 조인)"""
        try:
            nation = self.db.query(models.StatNation).filter(
                models.StatNation.user_no == user_no
            ).first()

            if not nation:
                return self._format_response(False, "Nation not found")

            alliance_member = self.db.query(models.AllianceMember).filter(
                models.AllianceMember.user_no == user_no
            ).first()

            return self._format_response(
                True, "Nation retrieved successfully",
                self._serialize_model(nation, alliance_member)
            )

        except SQLAlchemyError as e:
            self.logger.error(f"get_nation error: {e}")
            return self._format_response(False, f"Database error: {str(e)}")

    # ============================================
    # 동기화용 upsert
    # ============================================

    def upsert_nation(self, user_no: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redis nation 데이터를 MySQL에 upsert"""
        try:
            nation = self.db.query(models.StatNation).filter(
                models.StatNation.user_no == user_no
            ).first()

            if nation:
                nation.name = data.get('name', nation.name)
                nation.alliance_no = data.get('alliance_no', nation.alliance_no)
                nation.last_dt = datetime.utcnow()
            else:
                nation = models.StatNation(
                    user_no=user_no,
                    account_no=data.get('account_no', 0),
                    name=data.get('name'),
                    hq_lv = data.get('hq_lv',0),
                    power = data.get('power',0),
                    alliance_no=data.get('alliance_no'),
                    cr_dt=datetime.utcnow(),
                    last_dt=datetime.utcnow()
                )
                self.db.add(nation)

            self.db.flush()
            return self._format_response(True, f"Nation upserted for user {user_no}")

        except SQLAlchemyError as e:
            self.logger.error(f"upsert_nation error: {e}")
            return self._format_response(False, f"Database error: {str(e)}")

    # ============================================
    # 필드 단위 업데이트
    # ============================================

    def update_nation_fields(self, user_no: int, **update_fields) -> Dict[str, Any]:
        """특정 필드만 업데이트"""
        try:
            nation = self.db.query(models.StatNation).filter(
                models.StatNation.user_no == user_no
            ).first()

            if not nation:
                return self._format_response(False, "Nation not found")

            for field, value in update_fields.items():
                if hasattr(nation, field):
                    setattr(nation, field, value)

            nation.last_dt = datetime.utcnow()
            self.db.flush()
            return self._format_response(True, "Nation updated successfully")

        except SQLAlchemyError as e:
            self.logger.error(f"update_nation_fields error: {e}")
            return self._format_response(False, f"Database error: {str(e)}")