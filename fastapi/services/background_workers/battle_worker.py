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
    - 전장(battlefield) 집계 틱도 함께 전송
    """

    def __init__(self, redis_manager, websocket_manager=None, check_interval: float = 1.0):
        super().__init__(category="battle", check_interval=check_interval)
        self.redis_manager = redis_manager
        self.websocket_manager = websocket_manager

    def _create_db_session(self):
        return SessionLocal()

    async def _process_pending(self):
        """활성 전투 1라운드 처리 + 전장 집계 틱 전송"""
        combat_rm = self.redis_manager.get_combat_manager()
        active_battles = await combat_rm.get_active_battles()

        if active_battles:
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

                            # 맵 브로드캐스트: 전투 → 귀환 중으로 상태 갱신
                            if self.websocket_manager:
                                march_id = state.get("march_id")
                                if march_id:
                                    march_meta = await combat_rm.get_march_metadata(int(march_id))
                                    return_time_str = None
                                    if march_meta and march_meta.get("return_time"):
                                        return_time_str = march_meta["return_time"]
                                    await self.websocket_manager.broadcast_message({
                                        "type": "map_march_update",
                                        "data": {
                                            "march_id": int(march_id),
                                            "status": "returning",
                                            "return_time": return_time_str,
                                        }
                                    })
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

        # 개별 전투 처리 완료 후 전장 집계 틱 전송 (전투가 없어도 실행)
        await self._send_battlefield_ticks()

    async def _send_battlefield_ticks(self):
        """전장 1~3 각각에 대해 집계 틱을 생성하여 구독자에게 전송"""
        if not self.websocket_manager:
            return
        combat_rm = self.redis_manager.get_combat_manager()

        for bf_id in (1, 2, 3):
            battle_ids = await combat_rm.bf_get_battles(bf_id)
            if not battle_ids:
                continue

            battles_data = []
            for bid in battle_ids:
                state = await combat_rm.get_battle_state(bid)
                if not state or state.get("status") == "finished":
                    # 종료된 전투가 Set에 남아있으면 정리
                    await combat_rm.bf_remove_battle(bf_id, bid)
                    continue
                atk_max = int(state.get("atk_max_hp", 1)) or 1
                def_max = int(state.get("def_max_hp", 1)) or 1
                atk_hp = int(state.get("atk_hp", atk_max))
                def_hp = int(state.get("def_hp", def_max))
                battles_data.append([
                    bid,
                    int(state.get("to_x", 0)),
                    int(state.get("to_y", 0)),
                    int(atk_hp / atk_max * 100),
                    int(def_hp / def_max * 100),
                    int(state.get("round", 0)),
                ])

            if not battles_data:
                continue

            subscribers = await combat_rm.bf_get_subscribers(bf_id)
            if not subscribers:
                continue

            tick_msg = json.dumps({
                "type": "battlefield_tick",
                "bf_id": bf_id,
                "battles": battles_data,
            })
            for sub_no in subscribers:
                try:
                    await self.websocket_manager.send_personal_message(tick_msg, sub_no)
                except Exception as e:
                    self.logger.error(f"battlefield_tick send error bf={bf_id} user={sub_no}: {e}")

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
