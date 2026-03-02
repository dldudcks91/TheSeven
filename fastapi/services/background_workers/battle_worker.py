import json
import logging
from .base_worker import BaseWorker
from services.game.BattleManager import BattleManager
from services.db_manager import DBManager
from database import SessionLocal


class BattleWorker(BaseWorker):
    """
    전투 틱 워커 (1초 주기)
    - battle:active Set에서 활성 전투 목록 가져와 매 초 1라운드 처리
    """

    def __init__(self, redis_manager, websocket_manager=None, check_interval: float = 1.0):
        super().__init__(category="battle", check_interval=check_interval)
        self.redis_manager = redis_manager
        self.websocket_manager = websocket_manager

    def _create_db_session(self):
        return SessionLocal()

    async def _process_pending(self):
        """활성 전투 전체에 대해 1라운드 처리"""
        combat_rm = self.redis_manager.get_combat_manager()
        active_battles = await combat_rm.get_active_battles()
        if not active_battles:
            return

        db_session = self._create_db_session()
        db_manager = DBManager(db_session)
        battle_manager = BattleManager(db_manager, self.redis_manager)

        try:
            for battle_id in active_battles:
                try:
                    result = await battle_manager.process_battle_tick(battle_id)
                    if not result["success"]:
                        continue

                    state = await combat_rm.get_battle_state(battle_id)
                    if not state:
                        continue

                    attacker_no = int(state.get("attacker_no", 0))
                    defender_no = int(state.get("defender_no", 0))

                    if result["data"].get("finished"):
                        # 전투 종료 알림
                        finish_data = {
                            "battle_id": battle_id,
                            "result": result["data"].get("result"),
                        }
                        await self._notify(attacker_no, "battle_end", finish_data)
                        await self._notify(defender_no, "battle_end", finish_data)
                    else:
                        # 라운드 틱 알림 (현재 상태)
                        tick_data = {
                            "battle_id": battle_id,
                            "round": result["data"].get("round"),
                            "atk_units": state.get("atk_units"),
                            "def_units": state.get("def_units"),
                        }
                        await self._notify(attacker_no, "battle_tick", tick_data)
                        await self._notify(defender_no, "battle_tick", tick_data)

                except Exception as e:
                    self.logger.error(f"Battle tick error for battle_id={battle_id}: {e}")
        finally:
            db_session.close()

    async def _notify(self, user_no: int, msg_type: str, data: dict):
        if not self.websocket_manager or not user_no:
            return
        try:
            message = json.dumps({"type": msg_type, "data": data})
            await self.websocket_manager.send_personal_message(message, user_no)
        except Exception as e:
            self.logger.error(f"BattleWorker WS error: {e}")

    # BaseWorker 추상 메서드 (사용 안 함)
    async def _get_pending_users(self): pass
    async def _remove_from_pending(self, user_no): pass
    async def _sync_user(self, user_no, db_session): pass
