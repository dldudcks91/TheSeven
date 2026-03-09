import math
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from services.game.NationManager import NationManager
from services.game.MarchManager import MarchManager


class RallyManager:
    """
    집결(Rally) 관리자

    집결 흐름:
      1. Leader가 rally_create → recruit_window 시작
      2. 멤버가 rally_join → gather 행군 (기존 march 인프라 재사용)
      3. recruit_window 만료 + 전원 도착 → _try_launch_rally
      4. rally_attack 행군 → 도착 시 BattleManager.rally_npc_battle_start
      5. 전투 종료 → 멤버별 개별 return march (TaskWorker 처리)

    상태: recruiting → waiting → marching → done
    """

    RECRUIT_WINDOWS = {1: 1, 5: 5}  # 분 단위 선택지

    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None
        self.data: dict = {}

    def _format(self, success: bool, message: str, data: Any = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    def _get_nation_manager(self) -> NationManager:
        return NationManager(self.db_manager, self.redis_manager)

    # ─────────────────────────────────────────────
    # API: rally_create (9031)
    # ─────────────────────────────────────────────

    async def rally_create(self) -> Dict:
        """
        집결 생성 (Leader)
        data: {target_type, npc_id, units, hero_idx, recruit_window}
        """
        user_no = self.user_no
        target_type = self.data.get("target_type", "npc")
        npc_id = int(self.data.get("npc_id", 0))
        units_raw = self.data.get("units", {})
        units = {int(k): int(v) for k, v in units_raw.items()}
        hero_idx = self.data.get("hero_idx")
        recruit_window = int(self.data.get("recruit_window", 1))

        # 기본 검증
        if not units:
            return self._format(False, "units는 필수입니다")
        if target_type != "npc":
            return self._format(False, "현재 NPC 집결만 지원됩니다")
        if not npc_id:
            return self._format(False, "npc_id는 필수입니다")
        if recruit_window not in self.RECRUIT_WINDOWS:
            return self._format(False, f"recruit_window는 {list(self.RECRUIT_WINDOWS.keys())} 중 선택")

        # 연맹 체크
        nation_manager = self._get_nation_manager()
        nation = await nation_manager.get_nation(user_no)
        if not nation or not nation.get("alliance_no"):
            return self._format(False, "연맹에 가입되어 있지 않습니다")
        alliance_no = nation["alliance_no"]

        # NPC 검증
        npc_configs = GameDataManager.REQUIRE_CONFIGS.get("npc", {})
        if npc_id not in npc_configs:
            return self._format(False, f"존재하지 않는 NPC: {npc_id}")
        combat_rm = self.redis_manager.get_combat_manager()
        npc_instance = await combat_rm.get_npc(npc_id)
        if not npc_instance or not npc_instance.get("alive", False):
            return self._format(False, "NPC가 현재 처치 상태입니다")

        # 행군 슬롯 체크 + 영웅 중복 체크
        march_manager = MarchManager(self.db_manager, self.redis_manager)
        err = await march_manager._check_march_limits(user_no, hero_idx)
        if err:
            return err

        # 병력 검증
        err = await march_manager._validate_units(user_no, units)
        if err:
            return err

        # 위치 조회
        my_pos = await march_manager._get_position(user_no)
        if not my_pos:
            return self._format(False, "위치 정보를 찾을 수 없습니다")

        npc_cfg = npc_configs[npc_id]
        target_pos = {"x": npc_cfg["map_x"], "y": npc_cfg["map_y"]}

        # 병력 차감 (ready → field)
        await march_manager._deduct_units(user_no, units)

        # Rally 생성
        rally_id = await combat_rm.generate_rally_id()
        now = datetime.utcnow()
        recruit_expire = now + timedelta(minutes=self.RECRUIT_WINDOWS[recruit_window])

        rally_data = {
            "rally_id": rally_id,
            "leader_no": user_no,
            "alliance_no": alliance_no,
            "target_type": target_type,
            "npc_id": npc_id,
            "target_x": target_pos["x"],
            "target_y": target_pos["y"],
            "leader_x": my_pos["x"],
            "leader_y": my_pos["y"],
            "hero_idx": hero_idx,
            "recruit_window": recruit_window,
            "recruit_expire": recruit_expire.isoformat(),
            "recruit_expired": False,
            "status": "recruiting",
            "created_at": now.isoformat(),
        }
        await combat_rm.set_rally(rally_id, rally_data)

        # Leader를 멤버로 등록 (즉시 arrived — Leader는 본인 성에 있으므로)
        leader_member = {
            "user_no": user_no,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": hero_idx,
            "march_id": None,
            "status": "arrived",
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
        }
        await combat_rm.set_rally_member(rally_id, user_no, leader_member)

        # 행군 슬롯 소모 (Leader용 — march metadata는 rally_attack 시 생성)
        march_id = await combat_rm.generate_march_id()
        leader_march_meta = {
            "march_id": march_id,
            "user_no": user_no,
            "target_type": "rally_slot",
            "status": "rally_waiting",
            "rally_id": rally_id,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": hero_idx,
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
        }
        await combat_rm.set_march_metadata(march_id, leader_march_meta)
        await combat_rm.add_user_active_march(user_no, march_id)

        # Leader 멤버 데이터에 march_id 기록
        leader_member["march_id"] = march_id
        await combat_rm.set_rally_member(rally_id, user_no, leader_member)

        # 모집 만료 큐 등록
        await combat_rm.add_rally_recruit_to_queue(rally_id, recruit_expire)

        return self._format(True, "집결 생성 완료", {
            "rally_id": rally_id,
            "recruit_expire": recruit_expire.isoformat(),
            "recruit_window": recruit_window,
        })

    # ─────────────────────────────────────────────
    # API: rally_join (9032)
    # ─────────────────────────────────────────────

    async def rally_join(self) -> Dict:
        """
        집결 참여 (멤버)
        data: {rally_id, units}
        """
        user_no = self.user_no
        rally_id = int(self.data.get("rally_id", 0))
        units_raw = self.data.get("units", {})
        units = {int(k): int(v) for k, v in units_raw.items()}

        if not rally_id:
            return self._format(False, "rally_id는 필수입니다")
        if not units:
            return self._format(False, "units는 필수입니다")

        combat_rm = self.redis_manager.get_combat_manager()
        rally = await combat_rm.get_rally(rally_id)
        if not rally:
            return self._format(False, "집결을 찾을 수 없습니다")
        if rally["status"] != "recruiting":
            return self._format(False, f"참여 불가 상태: {rally['status']}")

        # 이미 참여 중인지 체크
        existing = await combat_rm.get_rally_member(rally_id, user_no)
        if existing:
            return self._format(False, "이미 참여 중입니다")

        # 같은 연맹 체크
        nation_manager = self._get_nation_manager()
        nation = await nation_manager.get_nation(user_no)
        if not nation or nation.get("alliance_no") != rally["alliance_no"]:
            return self._format(False, "같은 연맹만 참여 가능합니다")

        # 행군 슬롯 체크 (hero_idx 없음 — 멤버는 병사만 제공)
        march_manager = MarchManager(self.db_manager, self.redis_manager)
        err = await march_manager._check_march_limits(user_no, None)
        if err:
            return err

        # 병력 검증
        err = await march_manager._validate_units(user_no, units)
        if err:
            return err

        # 위치 조회
        my_pos = await march_manager._get_position(user_no)
        if not my_pos:
            return self._format(False, "위치 정보를 찾을 수 없습니다")

        # 병력 차감 (ready → field)
        await march_manager._deduct_units(user_no, units)

        # gather 행군 생성 (Leader 성 좌표로 이동)
        leader_x = rally["leader_x"]
        leader_y = rally["leader_y"]

        march_speed = march_manager._calc_march_speed(units)
        distance = march_manager._calc_distance(my_pos["x"], my_pos["y"], leader_x, leader_y)
        travel_minutes = distance / march_speed if march_speed > 0 else 1
        now = datetime.utcnow()
        arrival_time = now + timedelta(minutes=travel_minutes)

        march_id = await combat_rm.generate_march_id()
        march_meta = {
            "march_id": march_id,
            "user_no": user_no,
            "target_type": "rally_gather",
            "rally_id": rally_id,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": None,
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
            "to_x": leader_x,
            "to_y": leader_y,
            "march_speed": march_speed,
            "departure_time": now.isoformat(),
            "arrival_time": arrival_time.isoformat(),
            "return_time": None,
            "status": "marching",
        }
        await combat_rm.set_march_metadata(march_id, march_meta)
        await combat_rm.add_march_to_queue(march_id, arrival_time)
        await combat_rm.add_user_active_march(user_no, march_id)

        # 멤버 등록
        member_data = {
            "user_no": user_no,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": None,
            "march_id": march_id,
            "status": "gathering",
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
        }
        await combat_rm.set_rally_member(rally_id, user_no, member_data)

        ws = getattr(self, "websocket_manager", None)
        if ws:
            await ws.broadcast_message({
                "type": "map_march_start",
                "data": {
                    "march_id": march_id, "user_no": user_no,
                    "target_type": "rally_gather",
                    "from_x": my_pos["x"], "from_y": my_pos["y"],
                    "to_x": leader_x, "to_y": leader_y,
                    "departure_time": now.isoformat(),
                    "arrival_time": arrival_time.isoformat(),
                    "status": "marching",
                }
            })

        return self._format(True, "집결 참여 완료", {
            "rally_id": rally_id,
            "march_id": march_id,
            "arrival_time": arrival_time.isoformat(),
        })

    # ─────────────────────────────────────────────
    # API: rally_info (9033)
    # ─────────────────────────────────────────────

    async def rally_info(self) -> Dict:
        """집결 상세 조회 (data: rally_id)"""
        rally_id = int(self.data.get("rally_id", 0))
        if not rally_id:
            return self._format(False, "rally_id는 필수입니다")

        combat_rm = self.redis_manager.get_combat_manager()
        rally = await combat_rm.get_rally(rally_id)
        if not rally:
            return self._format(False, "집결을 찾을 수 없습니다")

        members = await combat_rm.get_all_rally_members(rally_id)
        members_list = []
        for uno, mdata in members.items():
            members_list.append({
                "user_no": uno,
                "units": mdata.get("units", {}),
                "status": mdata.get("status"),
            })

        return self._format(True, "OK", {
            "rally": rally,
            "members": members_list,
        })

    # ─────────────────────────────────────────────
    # API: rally_kick (9034)
    # ─────────────────────────────────────────────

    async def rally_kick(self) -> Dict:
        """
        집결 멤버 추방 (Leader만 가능)
        data: {rally_id, target_user_no}
        """
        user_no = self.user_no
        rally_id = int(self.data.get("rally_id", 0))
        target_user_no = int(self.data.get("target_user_no", 0))

        if not rally_id or not target_user_no:
            return self._format(False, "rally_id, target_user_no는 필수입니다")
        if user_no == target_user_no:
            return self._format(False, "자기 자신은 추방할 수 없습니다")

        combat_rm = self.redis_manager.get_combat_manager()
        rally = await combat_rm.get_rally(rally_id)
        if not rally:
            return self._format(False, "집결을 찾을 수 없습니다")
        if rally["leader_no"] != user_no:
            return self._format(False, "Leader만 추방할 수 있습니다")
        if rally["status"] not in ("recruiting", "waiting"):
            return self._format(False, f"추방 불가 상태: {rally['status']}")

        member = await combat_rm.get_rally_member(rally_id, target_user_no)
        if not member:
            return self._format(False, "해당 유저가 집결에 참여하고 있지 않습니다")

        # 멤버 제거 + 유닛 귀환 처리
        await self._remove_member_and_return(combat_rm, rally_id, target_user_no, member)

        return self._format(True, "추방 완료")

    # ─────────────────────────────────────────────
    # API: rally_cancel (9035)
    # ─────────────────────────────────────────────

    async def rally_cancel(self) -> Dict:
        """
        집결 취소 (Leader만 가능)
        data: {rally_id}
        """
        user_no = self.user_no
        rally_id = int(self.data.get("rally_id", 0))

        if not rally_id:
            return self._format(False, "rally_id는 필수입니다")

        combat_rm = self.redis_manager.get_combat_manager()
        rally = await combat_rm.get_rally(rally_id)
        if not rally:
            return self._format(False, "집결을 찾을 수 없습니다")
        if rally["leader_no"] != user_no:
            return self._format(False, "Leader만 취소할 수 있습니다")
        if rally["status"] in ("marching", "done"):
            return self._format(False, f"취소 불가 상태: {rally['status']}")

        # 모든 멤버 귀환 처리
        members = await combat_rm.get_all_rally_members(rally_id)
        for member_no, member_data in members.items():
            await self._remove_member_and_return(combat_rm, rally_id, member_no, member_data)

        # Rally 정리
        await combat_rm.remove_rally_recruit_from_queue(rally_id)
        await combat_rm.update_rally(rally_id, {"status": "done"})
        await combat_rm.delete_rally(rally_id)

        ws = getattr(self, "websocket_manager", None)
        if ws:
            await ws.broadcast_message({
                "type": "rally_cancelled",
                "data": {"rally_id": rally_id}
            })

        return self._format(True, "집결 취소됨")

    # ─────────────────────────────────────────────
    # 내부 헬퍼
    # ─────────────────────────────────────────────

    async def _remove_member_and_return(self, combat_rm, rally_id: int,
                                         member_no: int, member_data: Dict):
        """멤버를 집결에서 제거하고, 상태에 따라 유닛 귀환 처리"""
        status = member_data.get("status", "")
        march_id = member_data.get("march_id")
        units = member_data.get("units", {})

        if status == "gathering" and march_id:
            # 이동 중 → 행군 취소 + 즉시 유닛 복구 (field→ready)
            await combat_rm.remove_march_from_queue(march_id)
            unit_rm = self.redis_manager.get_unit_manager()
            for uid_str, count in units.items():
                unit_idx = int(uid_str)
                cached = await unit_rm.get_cached_unit(member_no, unit_idx)
                if cached:
                    cached["ready"] = int(cached.get("ready", 0)) + int(count)
                    cached["field"] = max(0, int(cached.get("field", 0)) - int(count))
                    await unit_rm.update_cached_unit(member_no, unit_idx, cached)
            await combat_rm.delete_march_metadata(march_id)
            await combat_rm.remove_user_active_march(member_no, march_id)

        elif status == "arrived" and march_id:
            # 도착 상태 → 본인 성으로 귀환 행군 생성
            from_x = member_data.get("from_x", 0)
            from_y = member_data.get("from_y", 0)

            rally = await combat_rm.get_rally(rally_id)
            leader_x = rally["leader_x"] if rally else 0
            leader_y = rally["leader_y"] if rally else 0

            march_manager = MarchManager(self.db_manager, self.redis_manager)
            march_speed = march_manager._calc_march_speed(
                {int(k): int(v) for k, v in units.items()}
            )
            distance = march_manager._calc_distance(leader_x, leader_y, from_x, from_y)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)

            # 기존 슬롯 march를 귀환 march로 전환
            await combat_rm.update_march_metadata(march_id, {
                "status": "returning",
                "target_type": "rally_return",
                "to_x": from_x,
                "to_y": from_y,
                "from_x": leader_x,
                "from_y": leader_y,
                "return_time": return_time.isoformat(),
                "march_speed": march_speed,
            })
            await combat_rm.add_march_return_to_queue(march_id, return_time)

        # 멤버 목록에서 제거
        await combat_rm.remove_rally_member(rally_id, member_no)

    async def try_launch_rally(self, rally_id: int):
        """
        발사 조건 체크 → 충족 시 rally_attack 행군 생성
        TaskWorker에서 호출 (recruit 만료 / gather 도착 시)
        """
        combat_rm = self.redis_manager.get_combat_manager()
        rally = await combat_rm.get_rally(rally_id)
        if not rally:
            return
        if rally["status"] not in ("recruiting", "waiting"):
            return

        recruit_expired = rally.get("recruit_expired", False)
        if not recruit_expired:
            return  # 아직 모집 중

        # 전원 도착 체크
        members = await combat_rm.get_all_rally_members(rally_id)
        if not members:
            return
        all_arrived = all(m.get("status") == "arrived" for m in members.values())
        if not all_arrived:
            # 아직 이동 중인 멤버 있음 → waiting 상태로 전환
            if rally["status"] != "waiting":
                await combat_rm.update_rally(rally_id, {"status": "waiting"})
            return

        # 발사 조건 충족 → rally_attack 행군 생성
        await combat_rm.update_rally(rally_id, {"status": "marching"})

        leader_x = rally["leader_x"]
        leader_y = rally["leader_y"]
        target_x = rally["target_x"]
        target_y = rally["target_y"]

        # 병합된 유닛 계산
        merged_units = {}
        for member_data in members.values():
            for uid_str, count in member_data.get("units", {}).items():
                uid = int(uid_str)
                merged_units[uid] = merged_units.get(uid, 0) + int(count)

        # 행군 속도 = 병합 유닛 중 최소 speed
        march_manager = MarchManager(self.db_manager, self.redis_manager)
        march_speed = march_manager._calc_march_speed(merged_units)
        distance = march_manager._calc_distance(leader_x, leader_y, target_x, target_y)
        travel_minutes = distance / march_speed if march_speed > 0 else 1
        now = datetime.utcnow()
        arrival_time = now + timedelta(minutes=travel_minutes)

        # rally_attack용 march metadata 생성
        march_id = await combat_rm.generate_march_id()
        march_meta = {
            "march_id": march_id,
            "user_no": rally["leader_no"],
            "target_type": "rally_attack",
            "rally_id": rally_id,
            "npc_id": rally.get("npc_id", 0),
            "units": {str(k): v for k, v in merged_units.items()},
            "hero_idx": rally.get("hero_idx"),
            "from_x": leader_x,
            "from_y": leader_y,
            "to_x": target_x,
            "to_y": target_y,
            "march_speed": march_speed,
            "departure_time": now.isoformat(),
            "arrival_time": arrival_time.isoformat(),
            "return_time": None,
            "status": "marching",
        }
        await combat_rm.set_march_metadata(march_id, march_meta)
        await combat_rm.add_march_to_queue(march_id, arrival_time)

        # rally에 attack march_id 기록
        await combat_rm.update_rally(rally_id, {"attack_march_id": march_id})

        ws = getattr(self, "websocket_manager", None)
        if ws:
            await ws.broadcast_message({
                "type": "rally_launched",
                "data": {
                    "rally_id": rally_id,
                    "march_id": march_id,
                    "from_x": leader_x, "from_y": leader_y,
                    "to_x": target_x, "to_y": target_y,
                    "departure_time": now.isoformat(),
                    "arrival_time": arrival_time.isoformat(),
                }
            })

        # 모든 참여자에게 WebSocket 알림
        for member_no in members:
            if ws:
                try:
                    import json
                    msg = json.dumps({
                        "type": "rally_march_start",
                        "data": {"rally_id": rally_id, "march_id": march_id,
                                 "arrival_time": arrival_time.isoformat()}
                    })
                    await ws.send_personal_message(msg, member_no)
                except Exception:
                    pass
