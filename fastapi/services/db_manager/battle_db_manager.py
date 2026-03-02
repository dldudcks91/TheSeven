import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
import models


class BattleDBManager:
    """전투 전용 DB 관리자 - Battle 테이블 CRUD"""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)

    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        return {"success": success, "message": message, "data": data or {}}

    def _serialize(self, b: models.Battle) -> Dict[str, Any]:
        return {
            "battle_id": b.battle_id,
            "march_id": b.march_id,
            "attacker_user_no": b.attacker_user_no,
            "defender_user_no": b.defender_user_no,
            "start_time": b.start_time.isoformat() if b.start_time else None,
            "end_time": b.end_time.isoformat() if b.end_time else None,
            "status": b.status,
            "total_rounds": b.total_rounds,
            "result": b.result,
            "attacker_loss": json.loads(b.attacker_loss) if b.attacker_loss else {},
            "defender_loss": json.loads(b.defender_loss) if b.defender_loss else {},
            "loot": json.loads(b.loot) if b.loot else {},
        }

    # ─────────────────────────────────────────────
    # INSERT
    # ─────────────────────────────────────────────

    def create_battle(self, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            battle = models.Battle(
                march_id=data["march_id"],
                attacker_user_no=data["attacker_user_no"],
                defender_user_no=data["defender_user_no"],
                start_time=datetime.utcnow(),
                status="active",
            )
            self.db.add(battle)
            self.db.flush()
            return self._format_response(True, "Battle created", self._serialize(battle))
        except Exception as e:
            self.logger.error(f"create_battle error: {e}")
            return self._format_response(False, str(e))

    # ─────────────────────────────────────────────
    # SELECT
    # ─────────────────────────────────────────────

    def get_battle(self, battle_id: int) -> Optional[Dict[str, Any]]:
        b = self.db.query(models.Battle).filter(models.Battle.battle_id == battle_id).first()
        return self._serialize(b) if b else None

    def get_user_battle_reports(self, user_no: int, limit: int = 20) -> List[Dict[str, Any]]:
        from sqlalchemy import or_
        rows = (
            self.db.query(models.Battle)
            .filter(
                or_(
                    models.Battle.attacker_user_no == user_no,
                    models.Battle.defender_user_no == user_no,
                ),
                models.Battle.status == "finished",
            )
            .order_by(models.Battle.end_time.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize(b) for b in rows]

    # ─────────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────────

    def finalize_battle(self, battle_id: int, total_rounds: int, result: str,
                        attacker_loss: Dict, defender_loss: Dict, loot: Dict) -> bool:
        b = self.db.query(models.Battle).filter(models.Battle.battle_id == battle_id).first()
        if not b:
            return False
        b.status = "finished"
        b.end_time = datetime.utcnow()
        b.total_rounds = total_rounds
        b.result = result
        b.attacker_loss = json.dumps(attacker_loss)
        b.defender_loss = json.dumps(defender_loss)
        b.loot = json.dumps(loot)
        return True
