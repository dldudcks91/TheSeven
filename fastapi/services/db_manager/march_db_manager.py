import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
import models


class MarchDBManager:
    """행군 전용 DB 관리자 - March 테이블 CRUD"""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)

    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        return {"success": success, "message": message, "data": data or {}}

    def _serialize(self, m: models.March) -> Dict[str, Any]:
        return {
            "march_id": m.march_id,
            "user_no": m.user_no,
            "target_type": m.target_type,
            "target_user_no": m.target_user_no,
            "from_x": m.from_x,
            "from_y": m.from_y,
            "to_x": m.to_x,
            "to_y": m.to_y,
            "units": json.loads(m.units) if m.units else {},
            "hero_idx": m.hero_idx,
            "march_speed": m.march_speed,
            "departure_time": m.departure_time.isoformat() if m.departure_time else None,
            "arrival_time": m.arrival_time.isoformat() if m.arrival_time else None,
            "return_time": m.return_time.isoformat() if m.return_time else None,
            "status": m.status,
            "battle_id": m.battle_id,
        }

    def _parse_dt(self, val) -> Optional[datetime]:
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None

    # ─────────────────────────────────────────────
    # INSERT
    # ─────────────────────────────────────────────

    def create_march(self, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            march = models.March(
                user_no=data["user_no"],
                target_type=data.get("target_type", "user"),
                target_user_no=data.get("target_user_no"),
                from_x=data["from_x"],
                from_y=data["from_y"],
                to_x=data["to_x"],
                to_y=data["to_y"],
                units=json.dumps(data["units"]),
                hero_idx=data.get("hero_idx"),
                march_speed=data["march_speed"],
                departure_time=self._parse_dt(data["departure_time"]),
                arrival_time=self._parse_dt(data["arrival_time"]),
                return_time=None,
                status="marching",
                battle_id=None,
            )
            self.db.add(march)
            self.db.flush()  # PK 확보
            return self._format_response(True, "March created", self._serialize(march))
        except Exception as e:
            self.logger.error(f"create_march error: {e}")
            return self._format_response(False, str(e))

    # ─────────────────────────────────────────────
    # SELECT
    # ─────────────────────────────────────────────

    def get_march(self, march_id: int) -> Optional[Dict[str, Any]]:
        m = self.db.query(models.March).filter(models.March.march_id == march_id).first()
        return self._serialize(m) if m else None

    def get_user_marches(self, user_no: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
        q = self.db.query(models.March).filter(models.March.user_no == user_no)
        if status:
            q = q.filter(models.March.status == status)
        return [self._serialize(m) for m in q.all()]

    def get_active_marches_against(self, target_user_no: int) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(models.March)
            .filter(
                models.March.target_user_no == target_user_no,
                models.March.status.in_(["marching", "battling"]),
            )
            .all()
        )
        return [self._serialize(m) for m in rows]

    # ─────────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────────

    def update_march_status(self, march_id: int, status: str,
                            battle_id: Optional[int] = None,
                            return_time: Optional[datetime] = None) -> bool:
        m = self.db.query(models.March).filter(models.March.march_id == march_id).first()
        if not m:
            return False
        m.status = status
        if battle_id is not None:
            m.battle_id = battle_id
        if return_time is not None:
            m.return_time = return_time
        return True
