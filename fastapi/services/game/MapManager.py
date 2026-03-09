import random
import logging
from typing import Dict, Any

from services.redis_manager import RedisManager
from services.db_manager import DBManager


class MapManager:
    """맵 관리자 - 유저 위치 조회/배정, 주변 유저 조회"""

    MAP_SIZE = 100  # 100×100 그리드

    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None
        self.data: dict = {}

    def _format(self, success: bool, message: str, data: Any = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    async def _ensure_position(self, user_no: int) -> Dict[str, int]:
        """유저 위치 반환. 없으면 빈 좌표에 랜덤 배정 후 저장."""
        combat_rm = self.redis_manager.get_combat_manager()
        pos = await combat_rm.get_position(user_no)
        if pos:
            return pos

        # Redis 미스 → DB 조회
        nation_dm = self.db_manager.get_nation_manager()
        result = nation_dm.get_user_nation(user_no)
        if result.get("success"):
            nation_data = result.get("data", {})
            if nation_data.get("map_x") is not None:
                x, y = nation_data["map_x"], nation_data["map_y"]
                await combat_rm.set_position(user_no, x, y)
                return {"x": x, "y": y}

        # 신규 배정: 점유되지 않은 좌표 탐색
        all_pos = await combat_rm.get_all_positions()
        occupied = {(p["x"], p["y"]) for p in all_pos.values()}

        x, y = 1, 1
        for _ in range(200):
            tx = random.randint(1, self.MAP_SIZE)
            ty = random.randint(1, self.MAP_SIZE)
            if (tx, ty) not in occupied:
                x, y = tx, ty
                break

        await combat_rm.set_position(user_no, x, y)
        # DB에도 저장
        nation_dm.update_nation_fields(user_no, map_x=x, map_y=y)
        self.db_manager.commit()

        return {"x": x, "y": y}

    # ─────────────────────────────────────────────
    # API 메서드 (APIManager 패턴: self.user_no / self.data)
    # ─────────────────────────────────────────────

    async def my_position(self) -> Dict:
        pos = await self._ensure_position(self.user_no)
        return self._format(True, "OK", pos)

    async def map_info(self) -> Dict:
        """현재 유저 중심 반경 내 다른 유저 목록 + 전체 활성 행군"""
        radius = int(self.data.get("radius", 20))
        my_pos = await self._ensure_position(self.user_no)
        combat_rm = self.redis_manager.get_combat_manager()
        nearby = await combat_rm.get_nearby_positions(my_pos["x"], my_pos["y"], radius)
        nearby = [p for p in nearby if p["user_no"] != self.user_no]
        # 활성 행군: march 큐에서 전체 march_id 조회 후 metadata 조합
        all_march_ids_raw = await combat_rm.redis.zrange(combat_rm.MARCH_QUEUE_KEY, 0, -1)
        return_ids_raw = await combat_rm.redis.zrange(combat_rm.MARCH_RETURN_QUEUE_KEY, 0, -1)
        all_march_ids = set(int(m) for m in all_march_ids_raw)
        all_march_ids.update(int(m) for m in return_ids_raw)
        all_marches = []
        for mid in all_march_ids:
            meta = await combat_rm.get_march_metadata(mid)
            if meta and meta.get("status") in ("marching", "battling", "returning"):
                all_marches.append(meta)
        return self._format(True, "OK", {
            "my_position": my_pos,
            "nearby": nearby,
            "map_size": self.MAP_SIZE,
            "all_marches": all_marches,
        })
