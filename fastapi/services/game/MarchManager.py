import math
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager


class MarchManager:
    """행군 관리자 - 출진/취소/목록 (Redis-only)"""

    MAX_MARCHES = 3        # 동시 행군 최대 수
    SPEED_FACTOR = 10      # unit.speed * SPEED_FACTOR = tiles/min

    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None
        self.data: dict = {}

    def _format(self, success: bool, message: str, data: Any = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    # ─────────────────────────────────────────────
    # 내부 헬퍼
    # ─────────────────────────────────────────────

    async def _get_position(self, user_no: int) -> Optional[Dict[str, int]]:
        combat_rm = self.redis_manager.get_combat_manager()
        pos = await combat_rm.get_position(user_no)
        if pos:
            return pos
        result = self.db_manager.get_nation_manager().get_user_nation(user_no)
        if result.get("success"):
            nd = result.get("data", {})
            if nd.get("map_x") is not None:
                x, y = nd["map_x"], nd["map_y"]
                await combat_rm.set_position(user_no, x, y)
                return {"x": x, "y": y}
        return None

    def _calc_distance(self, x1: int, y1: int, x2: int, y2: int) -> float:
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    def _calc_march_speed(self, units: Dict[int, int]) -> int:
        """행군 내 최소 speed * SPEED_FACTOR (tiles/min)"""
        unit_configs = GameDataManager.REQUIRE_CONFIGS.get("unit", {})
        speeds = []
        for unit_idx in units:
            cfg = unit_configs.get(unit_idx, {})
            speed = cfg.get("ability", {}).get("speed", 1)
            speeds.append(speed)
        min_speed = min(speeds) if speeds else 1
        return min_speed * self.SPEED_FACTOR

    async def _check_march_limits(self, user_no: int, hero_idx) -> Optional[Dict]:
        """동시 행군 수 + 영웅 중복 체크. 실패 시 에러 dict 반환, 통과 시 None"""
        combat_rm = self.redis_manager.get_combat_manager()
        march_ids = await combat_rm.get_user_active_march_ids(user_no)
        if len(march_ids) >= self.MAX_MARCHES:
            return self._format(False, f"최대 {self.MAX_MARCHES}개 행군만 가능합니다")

        if hero_idx:
            for mid in march_ids:
                meta = await combat_rm.get_march_metadata(mid)
                if meta and int(meta.get("hero_idx") or 0) == int(hero_idx):
                    if meta.get("status") in ("marching", "battling", "returning"):
                        return self._format(False, "해당 영웅은 이미 출전 중입니다")
        return None

    async def _validate_units(self, user_no: int, units: Dict[int, int]) -> Optional[Dict]:
        """병력 검증. 실패 시 에러 dict 반환, 통과 시 None"""
        unit_rm = self.redis_manager.get_unit_manager()
        for unit_idx, count in units.items():
            cached = await unit_rm.get_cached_unit(user_no, unit_idx)
            if not cached:
                return self._format(False, f"유닛 {unit_idx} 정보를 찾을 수 없습니다")
            ready = int(cached.get("ready", 0))
            if ready < count:
                return self._format(False, f"유닛 {unit_idx} 병력 부족 (보유: {ready}, 요청: {count})")
        return None

    async def _deduct_units(self, user_no: int, units: Dict[int, int]):
        """병력 차감 (ready → field)"""
        unit_rm = self.redis_manager.get_unit_manager()
        for unit_idx, count in units.items():
            cached = await unit_rm.get_cached_unit(user_no, unit_idx)
            cached["ready"] = int(cached["ready"]) - count
            cached["field"] = int(cached.get("field", 0)) + count
            await unit_rm.update_cached_unit(user_no, unit_idx, cached)

    # ─────────────────────────────────────────────
    # API 메서드 (APIManager 패턴: self.user_no / self.data)
    # ─────────────────────────────────────────────

    async def march_list(self) -> Dict:
        """유저의 활성 행군 목록"""
        user_no = self.user_no
        combat_rm = self.redis_manager.get_combat_manager()
        march_ids = await combat_rm.get_user_active_march_ids(user_no)

        marches = []
        for mid in march_ids:
            meta = await combat_rm.get_march_metadata(mid)
            if meta and meta.get("status") in ("marching", "battling", "returning"):
                marches.append(meta)
        return self._format(True, "OK", {"marches": marches})

    async def march_create(self) -> Dict:
        """출진 생성
        PvP: data = {target_type: "user", target_user_no, units, hero_idx}
        PvE: data = {target_type: "npc",  npc_id,           units, hero_idx}
        target_type 생략 시 "user"로 처리
        """
        user_no = self.user_no
        target_type = self.data.get("target_type", "user")
        units_raw = self.data.get("units", {})
        units = {int(k): int(v) for k, v in units_raw.items()}
        hero_idx = self.data.get("hero_idx")

        if not units:
            return self._format(False, "units는 필수입니다")

        # ── NPC 타겟 분기 ──────────────────────────────
        if target_type == "npc":
            return await self._march_create_npc(user_no, units, hero_idx)

        # ── 위치 이동 분기 ─────────────────────────────
        if target_type == "location":
            return await self._march_create_location(user_no, units, hero_idx)

        # ── PvP 타겟 ──────────────────────────────────
        target_user_no = int(self.data.get("target_user_no", 0))
        if not target_user_no:
            return self._format(False, "target_user_no는 필수입니다")
        if user_no == target_user_no:
            return self._format(False, "자신을 공격할 수 없습니다")

        # 1. 동시 행군 수 + 영웅 체크
        err = await self._check_march_limits(user_no, hero_idx)
        if err:
            return err

        # 2. 병력 검증
        err = await self._validate_units(user_no, units)
        if err:
            return err

        # 3. 위치 조회
        my_pos = await self._get_position(user_no)
        target_pos = await self._get_position(target_user_no)
        if not my_pos:
            return self._format(False, "위치 정보를 찾을 수 없습니다")
        if not target_pos:
            return self._format(False, "대상 유저 위치를 찾을 수 없습니다")

        # 4. 도착 시간 계산
        march_speed = self._calc_march_speed(units)
        distance = self._calc_distance(my_pos["x"], my_pos["y"], target_pos["x"], target_pos["y"])
        travel_minutes = distance / march_speed if march_speed > 0 else 1
        now = datetime.utcnow()
        arrival_time = now + timedelta(minutes=travel_minutes)

        # 5. 병력 차감 (ready→field)
        await self._deduct_units(user_no, units)

        # 6. Redis 행군 생성
        combat_rm = self.redis_manager.get_combat_manager()
        march_id = await combat_rm.generate_march_id()

        metadata = {
            "march_id": march_id,
            "user_no": user_no,
            "target_type": "user",
            "target_user_no": target_user_no,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": hero_idx,
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
            "to_x": target_pos["x"],
            "to_y": target_pos["y"],
            "march_speed": march_speed,
            "departure_time": now.isoformat(),
            "arrival_time": arrival_time.isoformat(),
            "return_time": None,
            "status": "marching",
            "battle_id": None,
        }
        await combat_rm.set_march_metadata(march_id, metadata)
        await combat_rm.add_march_to_queue(march_id, arrival_time)
        await combat_rm.add_user_active_march(user_no, march_id)

        ws = getattr(self, 'websocket_manager', None)
        if ws:
            await ws.broadcast_message({
                "type": "map_march_start",
                "data": {
                    "march_id": march_id, "user_no": user_no,
                    "target_type": "user",
                    "from_x": my_pos["x"], "from_y": my_pos["y"],
                    "to_x": target_pos["x"], "to_y": target_pos["y"],
                    "departure_time": now.isoformat(),
                    "arrival_time": arrival_time.isoformat(),
                    "return_time": None, "status": "marching",
                }
            })

        return self._format(True, "출진 완료", {
            "march_id": march_id,
            "arrival_time": arrival_time.isoformat(),
            "march_speed": march_speed,
            "distance": round(distance, 2),
        })

    async def _march_create_npc(self, user_no: int, units: Dict[int, int], hero_idx) -> Dict:
        """NPC 타겟 행군 생성"""
        npc_id = int(self.data.get("npc_id", 0))
        if not npc_id:
            return self._format(False, "npc_id는 필수입니다")

        npc_configs = GameDataManager.REQUIRE_CONFIGS.get('npc', {})
        if npc_id not in npc_configs:
            return self._format(False, f"존재하지 않는 NPC: {npc_id}")

        # NPC alive 확인
        combat_rm = self.redis_manager.get_combat_manager()
        npc_instance = await combat_rm.get_npc(npc_id)
        if not npc_instance or not npc_instance.get("alive", False):
            return self._format(False, "NPC가 현재 처치 상태입니다 (리스폰 대기 중)")

        # 동시 행군 수 + 영웅 체크
        err = await self._check_march_limits(user_no, hero_idx)
        if err:
            return err

        # 병력 검증
        err = await self._validate_units(user_no, units)
        if err:
            return err

        # 위치 조회
        my_pos = await self._get_position(user_no)
        if not my_pos:
            return self._format(False, "위치 정보를 찾을 수 없습니다")

        npc_cfg = npc_configs[npc_id]
        target_pos = {"x": npc_cfg["map_x"], "y": npc_cfg["map_y"]}

        # 도착 시간 계산
        march_speed = self._calc_march_speed(units)
        distance = self._calc_distance(my_pos["x"], my_pos["y"], target_pos["x"], target_pos["y"])
        travel_minutes = distance / march_speed if march_speed > 0 else 1
        now = datetime.utcnow()
        arrival_time = now + timedelta(minutes=travel_minutes)

        # 병력 차감 (ready→field)
        await self._deduct_units(user_no, units)

        # Redis 행군 생성
        march_id = await combat_rm.generate_march_id()

        metadata = {
            "march_id": march_id,
            "user_no": user_no,
            "target_type": "npc",
            "npc_id": npc_id,
            "target_user_no": 0,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": hero_idx,
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
            "to_x": target_pos["x"],
            "to_y": target_pos["y"],
            "march_speed": march_speed,
            "departure_time": now.isoformat(),
            "arrival_time": arrival_time.isoformat(),
            "return_time": None,
            "status": "marching",
            "battle_id": None,
        }
        await combat_rm.set_march_metadata(march_id, metadata)
        await combat_rm.add_march_to_queue(march_id, arrival_time)
        await combat_rm.add_user_active_march(user_no, march_id)

        ws = getattr(self, 'websocket_manager', None)
        if ws:
            await ws.broadcast_message({
                "type": "map_march_start",
                "data": {
                    "march_id": march_id, "user_no": user_no,
                    "target_type": "npc",
                    "from_x": my_pos["x"], "from_y": my_pos["y"],
                    "to_x": target_pos["x"], "to_y": target_pos["y"],
                    "departure_time": now.isoformat(),
                    "arrival_time": arrival_time.isoformat(),
                    "return_time": None, "status": "marching",
                }
            })

        return self._format(True, "NPC 출진 완료", {
            "march_id": march_id,
            "npc_id": npc_id,
            "arrival_time": arrival_time.isoformat(),
            "march_speed": march_speed,
            "distance": round(distance, 2),
        })

    async def _march_create_location(self, user_no: int, units: Dict[int, int], hero_idx) -> Dict:
        """위치 이동 행군 생성 — 빈 좌표로 이동 후 자동 귀환"""
        MAP_SIZE = 100
        to_x = self.data.get("to_x")
        to_y = self.data.get("to_y")
        if to_x is None or to_y is None:
            return self._format(False, "to_x, to_y는 필수입니다")
        to_x, to_y = int(to_x), int(to_y)
        if not (0 <= to_x <= MAP_SIZE and 0 <= to_y <= MAP_SIZE):
            return self._format(False, f"좌표 범위 초과 (0~{MAP_SIZE})")

        # 동시 행군 수 + 영웅 체크
        err = await self._check_march_limits(user_no, hero_idx)
        if err:
            return err

        # 병력 검증
        err = await self._validate_units(user_no, units)
        if err:
            return err

        my_pos = await self._get_position(user_no)
        if not my_pos:
            return self._format(False, "위치 정보를 찾을 수 없습니다")

        march_speed = self._calc_march_speed(units)
        distance = self._calc_distance(my_pos["x"], my_pos["y"], to_x, to_y)
        travel_minutes = distance / march_speed if march_speed > 0 else 1
        now = datetime.utcnow()
        arrival_time = now + timedelta(minutes=travel_minutes)
        return_time  = arrival_time + timedelta(minutes=travel_minutes)

        # 병력 차감
        await self._deduct_units(user_no, units)

        # Redis 행군 생성
        combat_rm = self.redis_manager.get_combat_manager()
        march_id = await combat_rm.generate_march_id()

        metadata = {
            "march_id": march_id,
            "user_no": user_no,
            "target_type": "location",
            "target_user_no": None,
            "units": {str(k): v for k, v in units.items()},
            "hero_idx": hero_idx,
            "from_x": my_pos["x"],
            "from_y": my_pos["y"],
            "to_x": to_x,
            "to_y": to_y,
            "march_speed": march_speed,
            "departure_time": now.isoformat(),
            "arrival_time": arrival_time.isoformat(),
            "return_time": return_time.isoformat(),
            "status": "marching",
            "battle_id": None,
        }
        await combat_rm.set_march_metadata(march_id, metadata)
        await combat_rm.add_march_to_queue(march_id, arrival_time)
        await combat_rm.add_user_active_march(user_no, march_id)

        ws = getattr(self, 'websocket_manager', None)
        if ws:
            await ws.broadcast_message({
                "type": "map_march_start",
                "data": {
                    "march_id": march_id, "user_no": user_no,
                    "target_type": "location",
                    "from_x": my_pos["x"], "from_y": my_pos["y"],
                    "to_x": to_x, "to_y": to_y,
                    "departure_time": now.isoformat(),
                    "arrival_time": arrival_time.isoformat(),
                    "return_time": return_time.isoformat(), "status": "marching",
                }
            })

        return self._format(True, "위치 이동 출진 완료", {
            "march_id": march_id,
            "arrival_time": arrival_time.isoformat(),
            "return_time":  return_time.isoformat(),
            "distance": round(distance, 2),
        })

    async def march_cancel(self) -> Dict:
        """행군 취소 (data: march_id)"""
        user_no = self.user_no
        march_id = int(self.data.get("march_id", 0))
        if not march_id:
            return self._format(False, "march_id는 필수입니다")

        combat_rm = self.redis_manager.get_combat_manager()
        march = await combat_rm.get_march_metadata(march_id)
        if not march:
            return self._format(False, "행군을 찾을 수 없습니다")
        if int(march.get("user_no", 0)) != user_no:
            return self._format(False, "권한 없음")
        if march.get("status") != "marching":
            return self._format(False, f"취소 불가 상태: {march['status']}")

        # 큐에서 제거
        await combat_rm.remove_march_from_queue(march_id)

        # 병력 복귀 (field→ready)
        unit_rm = self.redis_manager.get_unit_manager()
        units = march.get("units", {})
        for unit_idx_str, count in units.items():
            unit_idx = int(unit_idx_str)
            cached = await unit_rm.get_cached_unit(user_no, unit_idx)
            if cached:
                cached["ready"] = int(cached.get("ready", 0)) + count
                cached["field"] = max(0, int(cached.get("field", 0)) - count)
                await unit_rm.update_cached_unit(user_no, unit_idx, cached)

        # metadata 상태 업데이트 후 정리
        await combat_rm.update_march_metadata(march_id, {"status": "cancelled"})
        await combat_rm.remove_user_active_march(user_no, march_id)
        await combat_rm.delete_march_metadata(march_id)

        ws = getattr(self, 'websocket_manager', None)
        if ws:
            await ws.broadcast_message({
                "type": "map_march_complete",
                "data": {"march_id": march_id}
            })

        return self._format(True, "행군 취소됨")
