import logging
import json
import math
from datetime import datetime, timezone, timedelta
from .base_worker import BaseWorker
from services.game.UnitManager import UnitManager
from services.game.BuildingManager import BuildingManager  # 예시: 나중을 위해
from services.game.BattleManager import BattleManager
from services.game.RallyManager import RallyManager
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
            await self._handle_march_returns()

            # 4. NPC 리스폰 처리
            await self._handle_npc_respawns()

            # 5. 집결 모집 만료 처리
            await self._handle_rally_recruit_expires(db_manager)

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
                    await self._send_websocket_notification(user_no, 'unit_finish', result.get('data', {}))

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
                        event_data = result["data"]
                        await self._send_websocket_notification(
                            event_data["atk_user_no"], "battle_start", event_data
                        )
                        if self.websocket_manager:
                            await self.websocket_manager.broadcast_message({
                                "type": "map_march_update",
                                "data": {"march_id": march_id, "status": "battling", "return_time": None}
                            })
                elif target_type == "rally_gather":
                    # 집결 gather 도착 → 멤버 상태 arrived + launch 시도
                    rally_id = int(metadata.get("rally_id", 0)) if metadata else 0
                    user_no = int(metadata.get("user_no", 0)) if metadata else 0
                    if rally_id and user_no:
                        await combat_rm.update_march_metadata(march_id, {"status": "arrived"})
                        member = await combat_rm.get_rally_member(rally_id, user_no)
                        if member:
                            member["status"] = "arrived"
                            await combat_rm.set_rally_member(rally_id, user_no, member)
                        # launch 시도
                        rally_manager = RallyManager(db_manager, self.redis_manager)
                        rally_manager.websocket_manager = self.websocket_manager
                        await rally_manager.try_launch_rally(rally_id)

                elif target_type == "rally_attack":
                    # 집결 공격 도착 → rally NPC 전투 시작
                    rally_id = int(metadata.get("rally_id", 0)) if metadata else 0
                    npc_id = int(metadata.get("npc_id", 0)) if metadata else 0
                    if rally_id and npc_id:
                        result = await battle_manager.rally_npc_battle_start(march_id, npc_id, rally_id)
                        if result["success"]:
                            event_data = result["data"]
                            # 전체 참여자에게 battle_start 알림
                            rally_members = await combat_rm.get_all_rally_members(rally_id)
                            for member_no in rally_members:
                                await self._send_websocket_notification(
                                    member_no, "battle_start", event_data
                                )
                            if self.websocket_manager:
                                await self.websocket_manager.broadcast_message({
                                    "type": "map_march_update",
                                    "data": {"march_id": march_id, "status": "battling", "return_time": None}
                                })

                elif target_type == "location":
                    # 전투 없이 즉시 귀환 처리
                    user_no = int(metadata.get("user_no", 0)) if metadata else 0
                    return_time_str = metadata.get("return_time") if metadata else None
                    if return_time_str and user_no:
                        return_time = datetime.fromisoformat(return_time_str)
                        await combat_rm.update_march_metadata(march_id, {
                            "status": "returning",
                        })
                        await combat_rm.add_march_return_to_queue(march_id, return_time)
                        await self._send_websocket_notification(
                            user_no, "march_arrive", {"march_id": march_id}
                        )
                        if self.websocket_manager:
                            await self.websocket_manager.broadcast_message({
                                "type": "map_march_update",
                                "data": {"march_id": march_id, "status": "returning", "return_time": return_time_str}
                            })
                else:
                    result = await battle_manager.battle_start(march_id)
                    if result["success"]:
                        event_data = result["data"]
                        attacker_no = event_data["atk_user_no"]
                        defender_no = event_data["def_user_no"]

                        if event_data.get("bloodless"):
                            # 무혈입성: 전투 없이 즉시 약탈 완료 → 귀환 알림
                            await self._send_websocket_notification(
                                attacker_no, "battle_bloodless", event_data)
                            if defender_no:
                                await self._send_websocket_notification(
                                    defender_no, "battle_bloodless_defend", event_data)
                            if self.websocket_manager:
                                await self.websocket_manager.broadcast_message({
                                    "type": "map_march_update",
                                    "data": {
                                        "march_id": march_id,
                                        "status": "returning",
                                        "return_time": event_data.get("return_time"),
                                    }
                                })
                        else:
                            # 일반 전투 시작
                            await self._send_websocket_notification(
                                attacker_no, "battle_start", event_data)
                            if defender_no:
                                await self._send_websocket_notification(
                                    defender_no, "battle_start", event_data)
                                await self._send_websocket_notification(
                                    defender_no, "battle_incoming",
                                    {"battle_id": event_data["battle_id"]})
                            if self.websocket_manager:
                                await self.websocket_manager.broadcast_message({
                                    "type": "map_march_update",
                                    "data": {
                                        "march_id": march_id,
                                        "status": "battling",
                                        "return_time": None,
                                    }
                                })

                # 큐에서 제거 (battle_start에서 처리되지 않았을 경우 방어)
                await combat_rm.remove_march_from_queue(march_id)
        except Exception as e:
            self.logger.error(f"Error processing march arrivals: {e}")

    async def _handle_march_returns(self):
        """귀환 시간이 지난 행군 처리 — 유닛 field→ready 복구 포함"""
        try:
            combat_rm = self.redis_manager.get_combat_manager()
            march_ids = await combat_rm.get_pending_march_returns()
            if not march_ids:
                return

            for march_id in march_ids:
                march = await combat_rm.get_march_metadata(march_id)
                if not march:
                    await combat_rm.remove_march_return_from_queue(march_id)
                    continue

                user_no = int(march.get("user_no", 0))

                # 유닛 복구 (field → ready + death)
                if user_no:
                    await self._restore_units_on_return(user_no, march)

                # metadata 정리
                await combat_rm.remove_march_return_from_queue(march_id)
                await combat_rm.delete_march_metadata(march_id)
                if user_no:
                    await combat_rm.remove_user_active_march(user_no, march_id)

                await self._send_websocket_notification(
                    user_no, "march_return",
                    {"march_id": march_id}
                )
                if self.websocket_manager:
                    await self.websocket_manager.broadcast_message({
                        "type": "map_march_complete",
                        "data": {"march_id": march_id}
                    })
        except Exception as e:
            self.logger.error(f"Error processing march returns: {e}")

    async def _restore_units_on_return(self, user_no: int, march: dict):
        """귀환 완료 시 유닛 상태 복구: field → ready (생존) + death (손실)"""
        try:
            unit_rm = self.redis_manager.get_unit_manager()
            original_units = march.get("units", {})
            survived_units = march.get("survived_units", {})

            for uid_str, orig_count in original_units.items():
                unit_idx = int(uid_str)
                orig_count = int(orig_count)

                # survived_units가 없으면 (전투 없이 귀환: 취소/위치이동) 전원 생존
                survived = int(survived_units.get(str(unit_idx), orig_count))
                lost = orig_count - survived

                cached = await unit_rm.get_cached_unit(user_no, unit_idx)
                if cached:
                    cached["field"] = max(0, int(cached.get("field", 0)) - orig_count)
                    cached["ready"] = int(cached.get("ready", 0)) + survived
                    if lost > 0:
                        cached["death"] = int(cached.get("death", 0)) + lost
                    await unit_rm.update_cached_unit(user_no, unit_idx, cached)
        except Exception as e:
            self.logger.error(f"Error restoring units for user {user_no}: {e}")

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

    async def _handle_rally_recruit_expires(self, db_manager):
        """모집 시간이 만료된 집결 처리 → recruit_expired=True + launch 시도"""
        try:
            combat_rm = self.redis_manager.get_combat_manager()
            rally_ids = await combat_rm.get_pending_rally_recruit_expires()
            if not rally_ids:
                return

            for rally_id in rally_ids:
                rally = await combat_rm.get_rally(rally_id)
                if not rally or rally.get("status") not in ("recruiting", "waiting"):
                    await combat_rm.remove_rally_recruit_from_queue(rally_id)
                    continue

                # 모집 만료 표시
                await combat_rm.update_rally(rally_id, {"recruit_expired": True})
                await combat_rm.remove_rally_recruit_from_queue(rally_id)

                # launch 시도
                rally_manager = RallyManager(db_manager, self.redis_manager)
                rally_manager.websocket_manager = self.websocket_manager
                await rally_manager.try_launch_rally(rally_id)

        except Exception as e:
            self.logger.error(f"Error processing rally recruit expires: {e}")

    async def _send_websocket_notification(self, user_no: int, message_type: str, data: dict):
        """WebSocket으로 완료 알림 전송"""
        if not self.websocket_manager or not user_no:
            return
        try:
            message = json.dumps({
                'type': message_type,
                'user_no': user_no,
                'data': data,
            })
            await self.websocket_manager.send_personal_message(message, user_no)
        except Exception as e:
            self.logger.error(f"Error sending WebSocket notification: {e}")

    # BaseWorker의 추상 메서드이지만 Task 방식에서는 사용하지 않으므로 비워둡니다.
    async def _get_pending_users(self): pass
    async def _remove_from_pending(self, user_no): pass
    async def _sync_user(self, user_no, db_session): pass
