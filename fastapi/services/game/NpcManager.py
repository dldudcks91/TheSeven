import logging
from typing import Dict, Any

from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager


class NpcManager:
    """NPC 관리자 - 맵 위 NPC 초기화/조회"""

    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None
        self.data: dict = {}

    def _format(self, success: bool, message: str, data: Any = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    # ─────────────────────────────────────────────
    # 서버 시작 시 NPC 초기화 (main.py에서 호출)
    # ─────────────────────────────────────────────

    @classmethod
    async def initialize_npcs(cls, redis_manager: RedisManager):
        """메타데이터 기반으로 NPC 인스턴스를 Redis에 초기 배치"""
        logger = logging.getLogger(cls.__name__)
        combat_rm = redis_manager.get_combat_manager()
        npc_configs = GameDataManager.REQUIRE_CONFIGS.get('npc', {})

        if not npc_configs:
            logger.warning("NPC config is empty. Skipping NPC initialization.")
            return

        for npc_id, cfg in npc_configs.items():
            existing = await combat_rm.get_npc(npc_id)
            if existing is not None:
                # 서버 재시작 시 기존 인스턴스 유지 (alive 상태 보존)
                continue
            npc_instance = {
                "npc_id": npc_id,
                "npc_idx": npc_id,
                "x": cfg["map_x"],
                "y": cfg["map_y"],
                "alive": True,
                "respawn_at": None,
            }
            await combat_rm.set_npc(npc_id, npc_instance)

        logger.info(f"NPC initialization complete. {len(npc_configs)} NPCs registered.")

    # ─────────────────────────────────────────────
    # API 메서드
    # ─────────────────────────────────────────────

    async def npc_list(self) -> Dict:
        """9003 - 맵 위 NPC 목록 조회"""
        combat_rm = self.redis_manager.get_combat_manager()
        npc_instances = await combat_rm.get_all_npcs()
        npc_configs = GameDataManager.REQUIRE_CONFIGS.get('npc', {})

        npcs = []
        for npc_id, instance in npc_instances.items():
            cfg = npc_configs.get(npc_id, {})
            npcs.append({
                **instance,
                "korean_name": cfg.get("korean_name", ""),
                "english_name": cfg.get("english_name", ""),
                "tier": cfg.get("tier", 1),
                "exp_reward": cfg.get("exp_reward", 0),
            })

        return self._format(True, "OK", {"npcs": npcs})
