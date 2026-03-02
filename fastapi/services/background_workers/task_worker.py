import logging
import json
from datetime import datetime, timezone
from .base_worker import BaseWorker
from services.game.UnitManager import UnitManager
from services.game.BuildingManager import BuildingManager  # 예시: 나중을 위해
from services.game.BattleManager import BattleManager
from services.db_manager import DBManager
from database import SessionLocal


class TaskWorker(BaseWorker):
    """
    게임 내 시간 완료 작업(Task) 처리 통합 워커
    - Redis의 Task Queue를 감시하여 완료 시간이 지난 항목들을 처리합니다.
    """
    
    def __init__(self, redis_manager, websocket_manager = None, check_interval: float = 1.0):
        # 작업 처리는 실시간성이 중요하므로 기본 주기를 1초로 설정합니다.
        super().__init__(category='game_task', check_interval=check_interval)
        self.redis_manager = redis_manager
        self.websocket_manager = websocket_manager

    def _create_db_session(self):
        return SessionLocal()

    async def _process_pending(self):
        """매 주기마다 등록된 모든 카테고리의 태스크를 순차적으로 처리합니다."""
        db_session = self._create_db_session()
        db_manager = DBManager(db_session)
        
        try:
            # 1. 유닛 태스크 처리
            await self._handle_unit_tasks(db_manager)

            # 2. 행군 도착 처리
            await self._handle_march_arrivals(db_manager)

            # 3. 행군 귀환 처리
            await self._handle_march_returns(db_manager)

            # 4. NPC 리스폰 처리
            await self._handle_npc_respawns()
            
        except Exception as e:
            self.logger.error(f"[{self.category}] Error in TaskWorker loop: {e}", exc_info=True)
        finally:
            db_session.close()

    async def _handle_unit_tasks(self, db_manager):
        """완료된 유닛 훈련/업그레이드 태스크 처리"""
        try:
            unit_manager = UnitManager(db_manager, self.redis_manager)
            completed_tasks = await unit_manager.get_completed_units_for_worker()
            
            if not completed_tasks:
                return
            
            for task in completed_tasks:
                user_no = int(task.get('user_no'))
                task_id = task.get('task_id')
                sub_id = task.get('sub_id')
                    
                unit_manager.user_no = user_no
                unit_manager.data = {"unit_type": task_id, "unit_idx": sub_id}

                
                # finish_unit_internal이 캐시 갱신 및 DB 동기화 큐 삽입 처리
                #success = await unit_manager.finish_unit_internal(user_no, task_id)
                result = await unit_manager.unit_finish()
                
                if result and result.get('success'):
                    self.logger.info(f"Unit task {task_id} completed for user {user_no}")
                    await self._send_websocket_notification(user_no, 'unit_finish', result)
                    
        except Exception as e:
            self.logger.error(f"Error processing unit tasks: {e}")


    async def _handle_march_arrivals(self, db_manager):
        """도착 시간이 지난 행군 처리 → target_type에 따라 NPC/유저 전투 분기"""
        try:
            combat_rm = self.redis_manager.get_combat_manager()
            march_ids = await combat_rm.get_pending_march_arrivals()
            if not march_ids:
                return

            battle_manager = BattleManager(db_manager, self.redis_manager)
            for march_id in march_ids:
                metadata = await combat_rm.get_march_metadata(march_id)
                target_type = metadata.get("target_type", "user") if metadata else "user"

                if target_type == "npc":
                    npc_id = int(metadata.get("npc_id", 0)) if metadata else 0
                    result = await battle_manager.npc_battle_start(march_id, npc_id)
                    if result["success"]:
                        battle_id = result["data"].get("battle_id")
                        attacker_no = metadata["user_no"]
                        await self._send_websocket_notification(
                            attacker_no, "battle_start",
                            {"battle_id": battle_id, "battle_type": "npc", "npc_id": npc_id}
                        )
                else:
                    result = await battle_manager.battle_start(march_id)
                    if result["success"]:
                        battle_id = result["data"].get("battle_id")
                        march_info = db_manager.get_march_manager().get_march(march_id)
                        if march_info:
                            await self._send_websocket_notification(
                                march_info["user_no"], "battle_start",
                                {"battle_id": battle_id}
                            )
                            if march_info.get("target_user_no"):
                                await self._send_websocket_notification(
                                    march_info["target_user_no"], "battle_incoming",
                                    {"battle_id": battle_id}
                                )

                # 큐에서 제거 (battle_start에서 처리되지 않았을 경우 방어)
                await combat_rm.remove_march_from_queue(march_id)
        except Exception as e:
            self.logger.error(f"Error processing march arrivals: {e}")

    async def _handle_march_returns(self, db_manager):
        """귀환 시간이 지난 행군 처리"""
        try:
            combat_rm = self.redis_manager.get_combat_manager()
            march_ids = await combat_rm.get_pending_march_returns()
            if not march_ids:
                return

            march_dm = db_manager.get_march_manager()
            for march_id in march_ids:
                march = march_dm.get_march(march_id)
                if not march:
                    await combat_rm.remove_march_return_from_queue(march_id)
                    continue
                march_dm.update_march_status(march_id, "completed")
                db_manager.commit()
                await combat_rm.remove_march_return_from_queue(march_id)
                await combat_rm.delete_march_metadata(march_id)
                await combat_rm.invalidate_user_marches(march["user_no"])
                await self._send_websocket_notification(
                    march["user_no"], "march_return",
                    {"march_id": march_id}
                )
        except Exception as e:
            self.logger.error(f"Error processing march returns: {e}")

    async def _handle_npc_respawns(self):
        """리스폰 시간이 지난 NPC를 alive=true로 복구"""
        try:
            combat_rm = self.redis_manager.get_combat_manager()
            npc_ids = await combat_rm.get_pending_npc_respawns()
            if not npc_ids:
                return
            for npc_id in npc_ids:
                await combat_rm.set_npc_alive(npc_id, True)
                await combat_rm.remove_npc_respawn_from_queue(npc_id)
                self.logger.info(f"NPC {npc_id} respawned")
        except Exception as e:
            self.logger.error(f"Error processing NPC respawns: {e}")

    async def _send_websocket_notification(self, user_no: int, message_type:str, result: dict):
        """WebSocket으로 완료 알림 전송"""
        if not self.websocket_manager:
            return
        try:
            message = json.dumps({
                'type': message_type,
                'user_no': user_no,
                'data': result.get('data', {})
            })
            await self.websocket_manager.send_personal_message(message, user_no)
        except Exception as e:
            self.logger.error(f"Error sending WebSocket notification: {e}")

    # BaseWorker의 추상 메서드이지만 Task 방식에서는 사용하지 않으므로 비워둡니다.
    async def _get_pending_users(self): pass
    async def _remove_from_pending(self, user_no): pass
    async def _sync_user(self, user_no, db_session): pass