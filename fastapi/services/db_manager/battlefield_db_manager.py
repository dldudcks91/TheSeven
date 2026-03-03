import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
import models


class BattlefieldDBManager:
    """전장 전용 DB 관리자 - BattlefieldMember 테이블 CRUD"""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)

    def _serialize(self, row: models.BattlefieldMember) -> Dict[str, Any]:
        return {
            "id": row.id,
            "bf_id": row.bf_id,
            "user_no": row.user_no,
            "castle_x": row.castle_x,
            "castle_y": row.castle_y,
            "joined_at": row.joined_at.isoformat() if row.joined_at else None,
        }

    # ─────────────────────────────────────────────
    # SELECT
    # ─────────────────────────────────────────────

    def get_user_battlefield(self, user_no: int) -> Optional[Dict[str, Any]]:
        row = (
            self.db.query(models.BattlefieldMember)
            .filter(models.BattlefieldMember.user_no == user_no)
            .first()
        )
        return self._serialize(row) if row else None

    def get_bf_members(self, bf_id: int) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(models.BattlefieldMember)
            .filter(models.BattlefieldMember.bf_id == bf_id)
            .all()
        )
        return [self._serialize(r) for r in rows]

    # ─────────────────────────────────────────────
    # INSERT / UPDATE
    # ─────────────────────────────────────────────

    def join_battlefield(self, user_no: int, bf_id: int,
                         castle_x: int, castle_y: int) -> Dict[str, Any]:
        """전장 참여 등록 (기존 참여 기록 덮어쓰기)"""
        try:
            self.db.query(models.BattlefieldMember).filter(
                models.BattlefieldMember.user_no == user_no
            ).delete()

            row = models.BattlefieldMember(
                bf_id=bf_id,
                user_no=user_no,
                castle_x=castle_x,
                castle_y=castle_y,
                joined_at=datetime.utcnow(),
            )
            self.db.add(row)
            self.db.flush()
            return self._serialize(row)
        except Exception as e:
            self.logger.error(f"join_battlefield error: {e}")
            raise

    # ─────────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────────

    def retreat_battlefield(self, user_no: int) -> bool:
        """전장 후퇴 (레코드 삭제)"""
        deleted = (
            self.db.query(models.BattlefieldMember)
            .filter(models.BattlefieldMember.user_no == user_no)
            .delete()
        )
        return deleted > 0
