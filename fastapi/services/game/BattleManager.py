import json
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from services.game.MarchManager import MarchManager


class BattleManager:
    """
    전투 관리자

    전투 흐름:
      1. march_arrival → battle_start() 호출 (TaskWorker가 트리거)
      2. BattleWorker가 1초마다 calculate_round() 호출
      3. 한 쪽 전멸 or 50라운드 → battle_end() 호출
    """

    LOOT_RATIO = 0.20    # 20%
    DAMAGE_SCALE = 5000  # 데미지 스케일 상수 (C)
    DEFAULT_HERO_COEFFS = {"atk": 1.0, "def": 1.0, "hp": 1.0}
    RAGE_PER_ATTACK = 20   # 공격 시 기력 획득
    RAGE_PER_HIT = 5       # 피격 시 기력 획득 (공격자당)
    RAGE_MAX = 100          # 기력 상한 → 스킬 발동

    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None
        self.data: dict = {}

    def _format(self, success: bool, message: str, data: Any = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    # ─────────────────────────────────────────────
    # 영웅 계수 (CSV base_stat / 100 = 배율)
    # ─────────────────────────────────────────────

    @staticmethod
    def _hero_coefficients(hero_idx: Optional[int]) -> Dict[str, float]:
        """영웅 CSV 스탯을 백분율 계수로 변환. 105 → 1.05배"""
        if not hero_idx or str(hero_idx) == "None":
            return BattleManager.DEFAULT_HERO_COEFFS.copy()
        hero_configs = GameDataManager.REQUIRE_CONFIGS.get("hero", {})
        hero_cfg = hero_configs.get(int(hero_idx))
        if not hero_cfg:
            return BattleManager.DEFAULT_HERO_COEFFS.copy()
        return {
            "atk": float(hero_cfg.get("base_attack", 100)) / 100.0,
            "def": float(hero_cfg.get("base_defense", 100)) / 100.0,
            "hp": float(hero_cfg.get("base_health", 100)) / 100.0,
        }

    # ─────────────────────────────────────────────
    # 영웅 스킬 조회
    # ─────────────────────────────────────────────

    @staticmethod
    def _get_hero_skill(hero_idx: Optional[int]) -> Optional[Dict]:
        """hero_idx로 스킬 CSV 조회"""
        if not hero_idx or str(hero_idx) == "None":
            return None
        skill_configs = GameDataManager.REQUIRE_CONFIGS.get("hero_skill", {})
        for skill in skill_configs.values():
            if skill["hero_idx"] == int(hero_idx):
                return skill
        return None

    async def _get_defender_hero_idx(self, defender_no: int) -> Optional[int]:
        """수비자의 보유 영웅 idx 조회 (첫 번째 소유 영웅 — garrison hero 미구현)"""
        try:
            combat_rm = self.redis_manager.get_combat_manager()
            hero_key = f"user_data:{defender_no}:hero"
            heroes = await combat_rm.redis.hgetall(hero_key)
            if heroes:
                first_key = next(iter(heroes.keys()))
                return int(first_key)
        except Exception:
            pass
        return None

    @staticmethod
    def _check_rage_skill(rage: int, hero_idx: Optional[int]) -> tuple:
        """기력 체크 → (new_rage, skill_mult, skill_fired)"""
        skill_mult = 1.0
        skill_fired = False
        if rage >= BattleManager.RAGE_MAX and hero_idx and str(hero_idx) != "None":
            skill = BattleManager._get_hero_skill(hero_idx)
            if skill and skill["effect_type"] == "damage":
                skill_mult = 1.0 + skill["value"] / 100.0
                skill_fired = True
            rage -= BattleManager.RAGE_MAX
        return rage, skill_mult, skill_fired

    # ─────────────────────────────────────────────
    # 전투력 계산 (√count 스케일링)
    # ─────────────────────────────────────────────

    def _calc_army_stats(self, units: Dict[int, int],
                         hero_coeffs: Optional[Dict[str, float]] = None) -> Dict:
        """
        RoK 스타일 전투력 계산.
        - power  = Σ(unit_atk × √count) × hero_atk_coeff
        - defense = Σ(unit_def × √count) × hero_def_coeff
        - health  = Σ(unit_hp  × √count) × hero_hp_coeff
        """
        if hero_coeffs is None:
            hero_coeffs = self.DEFAULT_HERO_COEFFS
        unit_configs = GameDataManager.REQUIRE_CONFIGS.get("unit", {})

        total_power = 0.0
        total_defense = 0.0
        total_health = 0.0

        for unit_idx, count in units.items():
            if count <= 0:
                continue
            cfg = unit_configs.get(unit_idx, {}).get("ability", {})
            sqrt_count = math.sqrt(count)
            total_power += float(cfg.get("attack", 100)) * sqrt_count
            total_defense += float(cfg.get("defense", 100)) * sqrt_count
            total_health += float(cfg.get("health", 100)) * sqrt_count

        total_power *= hero_coeffs["atk"]
        total_defense *= hero_coeffs["def"]
        total_health *= hero_coeffs["hp"]

        return {
            "power": total_power,
            "defense": total_defense,
            "health": total_health,
            "alive_units": {k: v for k, v in units.items() if v > 0},
        }

    # ─────────────────────────────────────────────
    # 라운드 계산 (Python 구현 - C++ 포팅 예정)
    # ─────────────────────────────────────────────

    @staticmethod
    def calculate_round(atk_stats: Dict, def_stats: Dict,
                        atk_skill_mult: float = 1.0,
                        def_skill_mult: float = 1.0) -> Dict:
        """
        1라운드 전투 시뮬레이션 (RoK 스타일).

        공식: Kills = C × atk_power / (def_defense × def_health) × skill_mult
        양측 동시 공격 후 사망 처리. 저티어부터 순차 제거.
        skill_mult: 스킬 발동 시 킬 배율 (default 1.0 = 스킬 없음)

        TODO: C++ pybind11 포팅 후 벤치마크 비교
        """
        C = BattleManager.DAMAGE_SCALE

        def calc_kills(attacker_power: float, defender_def: float,
                       defender_hp: float) -> float:
            """공격측이 방어측에 입히는 킬 수 계산"""
            if defender_def <= 0 or defender_hp <= 0:
                return 0.0
            return C * attacker_power / (defender_def * defender_hp)

        def distribute_kills(kills: float,
                             defender_units: Dict[int, int]) -> Dict[int, int]:
            """킬 수를 저티어(unit_idx 오름차순)부터 배분"""
            loss = {}
            remaining_kills = kills
            for unit_idx in sorted(defender_units.keys()):
                if remaining_kills < 1.0:
                    break
                count = defender_units[unit_idx]
                killed = min(int(remaining_kills), count)
                if killed > 0:
                    loss[unit_idx] = killed
                    remaining_kills -= killed
            return loss

        atk_units = dict(atk_stats.get("alive_units", {}))
        def_units = dict(def_stats.get("alive_units", {}))

        # 동시 공격 (같은 스냅샷 기준, 스킬 배율 적용)
        kills_to_def = calc_kills(atk_stats["power"], def_stats["defense"], def_stats["health"]) * atk_skill_mult
        kills_to_atk = calc_kills(def_stats["power"], atk_stats["defense"], atk_stats["health"]) * def_skill_mult

        def_loss = distribute_kills(kills_to_def, def_units)
        atk_loss = distribute_kills(kills_to_atk, atk_units)

        # 생존 병력 계산
        for uid, lost in def_loss.items():
            def_units[uid] = max(0, def_units.get(uid, 0) - lost)
        for uid, lost in atk_loss.items():
            atk_units[uid] = max(0, atk_units.get(uid, 0) - lost)

        atk_alive = {k: v for k, v in atk_units.items() if v > 0}
        def_alive = {k: v for k, v in def_units.items() if v > 0}

        return {
            "atk_loss": atk_loss,
            "def_loss": def_loss,
            "atk_alive": atk_alive,
            "def_alive": def_alive,
        }

    # ─────────────────────────────────────────────
    # NPC 전투 시작 (march 도착 시 TaskWorker가 호출)
    # ─────────────────────────────────────────────

    async def npc_battle_start(self, march_id: int, npc_id: int) -> Dict:
        """NPC 행군 도착 → NPC 전투 시작"""
        battle_dm = self.db_manager.get_battle_manager()
        combat_rm = self.redis_manager.get_combat_manager()

        march = await combat_rm.get_march_metadata(march_id)
        if not march:
            return self._format(False, "행군 정보 없음")
        if march.get("status") != "marching":
            return self._format(False, "이미 처리된 행군")

        attacker_no = int(march["user_no"])
        atk_units = {int(k): int(v) for k, v in march["units"].items()}

        # NPC 방어 병력
        npc_configs = GameDataManager.REQUIRE_CONFIGS.get('npc', {})
        npc_cfg = npc_configs.get(npc_id)
        if not npc_cfg:
            return self._format(False, f"NPC {npc_id} 메타데이터 없음")
        def_units = dict(npc_cfg["units"])  # {unit_idx: count}

        # NPC alive 체크 (이미 처치 상태 방어)
        npc_instance = await combat_rm.get_npc(npc_id)
        if not npc_instance or not npc_instance.get("alive", True):
            # NPC 처치 상태: 전투 없이 귀환
            await combat_rm.update_march_metadata(march_id, {"status": "returning"})
            return self._format(False, "NPC가 이미 처치된 상태")

        # 영웅 계수 조회 (CSV 기반, 레벨 무관)
        hero_coeffs = self._hero_coefficients(march.get("hero_idx"))

        # Battle DB 생성 (defender_user_no=0: NPC)
        result = battle_dm.create_battle({
            "march_id": march_id,
            "attacker_user_no": attacker_no,
            "defender_user_no": 0,
        })
        if not result["success"]:
            return self._format(False, "전투 생성 실패")

        battle_id = result["data"]["battle_id"]
        await combat_rm.update_march_metadata(march_id, {"status": "battling", "battle_id": battle_id})
        self.db_manager.commit()

        atk_stats = self._calc_army_stats(atk_units, hero_coeffs)
        def_stats = self._calc_army_stats(def_units)

        # 전장 참여 여부 확인 (전장 내 전투 추적용)
        bf_id = await combat_rm.get_user_battlefield(attacker_no) or 0

        await combat_rm.set_battle_state(battle_id, {
            "battle_id": battle_id,
            "march_id": march_id,
            "battle_type": "npc",
            "npc_id": npc_id,
            "hero_idx": march.get("hero_idx"),
            "def_hero_idx": None,  # NPC는 영웅 없음
            "attacker_no": attacker_no,
            "defender_no": 0,
            "atk_units": atk_units,
            "def_units": def_units,
            "atk_max_hp": atk_stats["health"],
            "def_max_hp": def_stats["health"],
            "atk_hp": atk_stats["health"],
            "def_hp": def_stats["health"],
            "to_x": march.get("to_x", 0),
            "to_y": march.get("to_y", 0),
            "bf_id": bf_id,
            "round": 0,
            "atk_rage": 0,
            "def_rage": 0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "status": "active",
        })
        await combat_rm.add_active_battle(battle_id)
        if bf_id:
            await combat_rm.bf_add_battle(bf_id, battle_id)

        return self._format(True, "NPC 전투 시작", {
            "battle_id": battle_id,
            "battle_type": "npc",
            "x": march.get("to_x"),
            "y": march.get("to_y"),
            "atk_user_no": attacker_no,
            "atk_hero_idx": march.get("hero_idx"),
            "atk_max_hp": atk_stats["health"],
            "atk_units": atk_units,
            "def_user_no": 0,
            "def_npc_id": npc_id,
            "def_max_hp": def_stats["health"],
            "def_units": def_units,
        })

    # ─────────────────────────────────────────────
    # 전투 시작 (march 도착 시 TaskWorker가 호출)
    # ─────────────────────────────────────────────

    async def battle_start(self, march_id: int) -> Dict:
        """행군 도착 → 전투 시작 (무혈입성 포함)"""
        battle_dm = self.db_manager.get_battle_manager()
        combat_rm = self.redis_manager.get_combat_manager()

        march = await combat_rm.get_march_metadata(march_id)
        if not march:
            return self._format(False, "행군 정보 없음")
        if march.get("status") != "marching":
            return self._format(False, "이미 처리된 행군")

        attacker_no = int(march["user_no"])
        defender_no = int(march["target_user_no"])
        atk_units = {int(k): int(v) for k, v in march["units"].items()}

        # 방어 병력: Redis 캐시에서 defender ready 병력
        unit_rm = self.redis_manager.get_unit_manager()
        def_units = {}
        cached_def = await unit_rm.get_cached_units(defender_no)
        if cached_def:
            for uid_str, udata in cached_def.items():
                ready = int(udata.get("ready", 0))
                if ready > 0:
                    def_units[int(uid_str)] = ready

        # 영웅 계수 조회 (CSV 기반, 레벨 무관)
        hero_coeffs = self._hero_coefficients(march.get("hero_idx"))

        # 수비자 영웅 조회
        def_hero_idx = await self._get_defender_hero_idx(defender_no)
        def_hero_coeffs = self._hero_coefficients(def_hero_idx)

        # ── 기존 진행 중 전투가 있으면 현재 수비 상태 동기화 ──
        def_units_original = dict(def_units)  # ready 캐시 기준 원본 (deduct용)
        existing_castle_bids = await combat_rm.get_castle_battles(defender_no)
        if existing_castle_bids:
            for existing_bid in existing_castle_bids:
                existing_state = await combat_rm.get_battle_state(existing_bid)
                if existing_state and existing_state.get("status") == "active":
                    # 진행 중 전투의 현재 수비 병력으로 동기화
                    def_units = {int(k): int(v) for k, v in existing_state.get("def_units", {}).items()}
                    break

        # ── 무혈입성: 수비 병력 0이면 전투 없이 즉시 약탈 ──
        if not def_units:
            return await self._bloodless_entry(
                march_id, march, attacker_no, defender_no, atk_units, 0)

        # 전투 DB 생성
        result = battle_dm.create_battle({
            "march_id": march_id,
            "attacker_user_no": attacker_no,
            "defender_user_no": defender_no,
        })
        if not result["success"]:
            return self._format(False, "전투 생성 실패")

        battle_id = result["data"]["battle_id"]

        # March 상태 업데이트 (Redis metadata)
        await combat_rm.update_march_metadata(march_id, {"status": "battling", "battle_id": battle_id})
        self.db_manager.commit()

        # Redis 전투 상태 초기화
        atk_stats = self._calc_army_stats(atk_units, hero_coeffs)
        def_stats = self._calc_army_stats(def_units, def_hero_coeffs)

        # 전장 참여 여부 확인
        bf_id = await combat_rm.get_user_battlefield(attacker_no) or 0

        await combat_rm.set_battle_state(battle_id, {
            "battle_id": battle_id,
            "march_id": march_id,
            "battle_type": "user",
            "attacker_no": attacker_no,
            "defender_no": defender_no,
            "hero_idx": march.get("hero_idx"),
            "def_hero_idx": def_hero_idx,
            "atk_units": atk_units,
            "def_units": def_units,
            "atk_max_hp": atk_stats["health"],
            "def_max_hp": def_stats["health"],
            "atk_hp": atk_stats["health"],
            "def_hp": def_stats["health"],
            "to_x": march.get("to_x", 0),
            "to_y": march.get("to_y", 0),
            "bf_id": bf_id,
            "round": 0,
            "atk_rage": 0,
            "def_rage": 0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "damage_dealt": 0,
            "def_units_original": def_units_original,
            "status": "active",
        })
        await combat_rm.add_active_battle(battle_id)
        await combat_rm.add_castle_battle(defender_no, battle_id)
        if bf_id:
            await combat_rm.bf_add_battle(bf_id, battle_id)

        return self._format(True, "전투 시작", {
            "battle_id": battle_id,
            "battle_type": "user",
            "x": march.get("to_x"),
            "y": march.get("to_y"),
            "atk_user_no": attacker_no,
            "atk_hero_idx": march.get("hero_idx"),
            "atk_max_hp": atk_stats["health"],
            "atk_units": atk_units,
            "def_user_no": defender_no,
            "def_max_hp": def_stats["health"],
            "def_units": def_units,
        })

    async def _bloodless_entry(self, march_id: int, march: Dict,
                                attacker_no: int, defender_no: int,
                                atk_units: Dict, hero_lv: int = 0) -> Dict:
        """수비 병력 0 → 전투 없이 즉시 약탈 + 귀환"""
        battle_dm = self.db_manager.get_battle_manager()
        combat_rm = self.redis_manager.get_combat_manager()
        resource_rm = self.redis_manager.get_resource_manager()

        # 약탈 계산
        loot = {}
        def_resources = await resource_rm.get_cached_all_resources(defender_no)
        if def_resources:
            for res_type in ("food", "wood", "stone", "gold"):
                amt = int(def_resources.get(res_type, 0))
                looted = int(amt * self.LOOT_RATIO)
                if looted > 0:
                    loot[res_type] = looted
            for res_type, looted in loot.items():
                await resource_rm.change_resource_amount(defender_no, res_type, -looted)
                await resource_rm.change_resource_amount(attacker_no, res_type, looted)

        # DB 전투 기록 (즉시 완료)
        result = battle_dm.create_battle({
            "march_id": march_id,
            "attacker_user_no": attacker_no,
            "defender_user_no": defender_no,
        })
        if result["success"]:
            battle_id = result["data"]["battle_id"]
            battle_dm.finalize_battle(
                battle_id=battle_id, total_rounds=0, result="attacker_win",
                attacker_loss={}, defender_loss={}, loot=loot,
            )
        self.db_manager.commit()

        # 귀환 march
        march_speed = int(march.get("march_speed", 1))
        from_x, from_y = int(march["from_x"]), int(march["from_y"])
        to_x, to_y = int(march["to_x"]), int(march["to_y"])
        distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
        travel_min = distance / march_speed if march_speed > 0 else 1
        return_time = datetime.utcnow() + timedelta(minutes=travel_min)
        await combat_rm.update_march_metadata(march_id, {
            "status": "returning",
            "return_time": return_time.isoformat(),
            "survived_units": {str(k): v for k, v in atk_units.items()},
        })
        await combat_rm.add_march_return_to_queue(march_id, return_time)

        return self._format(True, "무혈입성", {
            "bloodless": True,
            "battle_id": result["data"]["battle_id"] if result["success"] else 0,
            "battle_type": "user",
            "x": march.get("to_x"),
            "y": march.get("to_y"),
            "atk_user_no": attacker_no,
            "atk_hero_lv": hero_lv,
            "def_user_no": defender_no,
            "loot": loot,
            "return_time": return_time.isoformat(),
        })

    # ─────────────────────────────────────────────
    # 전투 틱 (BattleWorker가 1초마다 호출)
    # ─────────────────────────────────────────────

    async def process_battle_tick(self, battle_id: int) -> Dict:
        """1라운드 처리 (기력/스킬 포함)"""
        combat_rm = self.redis_manager.get_combat_manager()
        state = await combat_rm.get_battle_state(battle_id)
        if not state or state.get("status") != "active":
            return self._format(False, "비활성 전투")

        current_round = int(state.get("round", 0))
        atk_units = state.get("atk_units", {})
        def_units = state.get("def_units", {})

        # 정수 키 보장
        atk_units = {int(k): int(v) for k, v in atk_units.items()}
        def_units = {int(k): int(v) for k, v in def_units.items()}

        # 영웅 계수 (state에 저장된 hero_idx로 런타임 조회)
        atk_hero_idx = state.get("hero_idx")
        def_hero_idx = state.get("def_hero_idx")
        hero_coeffs = self._hero_coefficients(atk_hero_idx)
        def_hero_coeffs = self._hero_coefficients(def_hero_idx)

        # 기력 누적: 공격 시 +20, 피격 시 +5 (공격자당 1명씩)
        atk_rage = int(state.get("atk_rage", 0))
        def_rage = int(state.get("def_rage", 0))
        atk_rage += self.RAGE_PER_ATTACK   # 공격 시 +20
        def_rage += self.RAGE_PER_HIT       # 피격 시 +5 (1:1 전투이므로 공격자 1명)
        # 수비도 공격하므로 수비도 공격 기력 획득, 공격자도 피격 기력 획득
        def_rage += self.RAGE_PER_ATTACK
        atk_rage += self.RAGE_PER_HIT

        # 기력 스킬 체크
        atk_rage, atk_skill_mult, _ = self._check_rage_skill(atk_rage, atk_hero_idx)
        def_rage, def_skill_mult, _ = self._check_rage_skill(def_rage, def_hero_idx)

        # 전투력 산출 (RoK 스타일: √count × stat × hero_coeff)
        atk_stats = self._calc_army_stats(atk_units, hero_coeffs)
        def_stats = self._calc_army_stats(def_units, def_hero_coeffs)

        # 라운드 계산 (스킬 배율 적용)
        round_result = self.calculate_round(atk_stats, def_stats, atk_skill_mult, def_skill_mult)
        new_round = current_round + 1

        # 누적 손실 갱신
        atk_total_loss = state.get("atk_total_loss", {})
        def_total_loss = state.get("def_total_loss", {})
        for uid, lost in round_result["atk_loss"].items():
            key = str(uid)
            atk_total_loss[key] = int(atk_total_loss.get(key, 0)) + lost
        for uid, lost in round_result["def_loss"].items():
            key = str(uid)
            def_total_loss[key] = int(def_total_loss.get(key, 0)) + lost

        # 라운드 후 남은 병력으로 현재 health 계산
        new_atk_stats = self._calc_army_stats(round_result["atk_alive"], hero_coeffs)
        new_def_stats = self._calc_army_stats(round_result["def_alive"], def_hero_coeffs)

        # 상태 업데이트 (atk_hp/def_hp도 함께 저장 → battlefield_tick에서 사용)
        await combat_rm.set_battle_state(battle_id, {
            **state,
            "round": new_round,
            "atk_units": round_result["atk_alive"],
            "def_units": round_result["def_alive"],
            "atk_total_loss": atk_total_loss,
            "def_total_loss": def_total_loss,
            "atk_hp": new_atk_stats["health"],
            "def_hp": new_def_stats["health"],
            "atk_rage": atk_rage,
            "def_rage": def_rage,
        })

        # 종료 조건 체크 (한 쪽 전멸 시에만 종료, 라운드 제한 없음)
        atk_dead = not round_result["atk_alive"]
        def_dead = not round_result["def_alive"]

        if atk_dead or def_dead:
            if atk_dead and def_dead:
                result_str = "draw"
            elif def_dead:
                result_str = "attacker_win"
            else:
                result_str = "defender_win"

            battle_type = state.get("battle_type", "user")
            if battle_type == "npc":
                await self._npc_battle_end(battle_id, state, new_round, result_str,
                                           round_result["atk_alive"],
                                           atk_total_loss, def_total_loss)
            elif battle_type == "rally_npc":
                await self._rally_npc_battle_end(battle_id, state, new_round, result_str,
                                                 round_result["atk_alive"],
                                                 atk_total_loss, def_total_loss)
            else:
                await self._battle_end(battle_id, state, new_round, result_str,
                                       round_result["atk_alive"], round_result["def_alive"],
                                       atk_total_loss, def_total_loss)
            return self._format(True, "전투 종료", {"finished": True, "result": result_str})

        return self._format(True, f"Round {new_round}", {"finished": False, "round": new_round})

    # ─────────────────────────────────────────────
    # NPC 전투 종료
    # ─────────────────────────────────────────────

    async def _npc_battle_end(self, battle_id: int, state: Dict, total_rounds: int,
                              result: str, atk_alive: Dict,
                              atk_total_loss: Dict, def_total_loss: Dict):
        combat_rm = self.redis_manager.get_combat_manager()
        battle_dm = self.db_manager.get_battle_manager()

        attacker_no = int(state["attacker_no"])
        march_id = int(state["march_id"])
        npc_id = int(state.get("npc_id", 0))

        # 공격자 승리 시 영웅 EXP 지급
        if result == "attacker_win" and state.get("hero_idx"):
            hero_idx = int(state["hero_idx"])
            npc_cfg = GameDataManager.REQUIRE_CONFIGS.get('npc', {}).get(npc_id, {})
            exp_reward = int(npc_cfg.get("exp_reward", 0))
            if exp_reward > 0:
                hero_dm = self.db_manager.get_hero_manager()
                hero_dm.add_hero_exp(attacker_no, hero_idx, exp_reward)
                # Redis hero 캐시 무효화
                try:
                    hero_cache_key = f"user_data:{attacker_no}:hero"
                    await combat_rm.redis.delete(hero_cache_key)
                except Exception:
                    pass

        # NPC 처치: alive=false, 리스폰 큐 등록
        if result in ("attacker_win", "draw") and npc_id:
            npc_cfg = GameDataManager.REQUIRE_CONFIGS.get('npc', {}).get(npc_id, {})
            respawn_min = int(npc_cfg.get("respawn_minutes", 5))
            respawn_time = datetime.utcnow() + timedelta(minutes=respawn_min)
            npc_instance = await combat_rm.get_npc(npc_id)
            if npc_instance:
                npc_instance["alive"] = False
                npc_instance["respawn_at"] = respawn_time.isoformat()
                await combat_rm.set_npc(npc_id, npc_instance)
            await combat_rm.add_npc_respawn_to_queue(npc_id, respawn_time)

        # DB 전투 결과 저장
        battle_dm.finalize_battle(
            battle_id=battle_id,
            total_rounds=total_rounds,
            result=result,
            attacker_loss={k: v for k, v in atk_total_loss.items()},
            defender_loss={k: v for k, v in def_total_loss.items()},
            loot={},
        )
        self.db_manager.commit()

        # 귀환 큐 등록 (유닛 복구는 귀환 완료 시 TaskWorker가 처리)
        march = await combat_rm.get_march_metadata(march_id)
        if march:
            march_speed = int(march.get("march_speed", 1))
            from_x, from_y = int(march["from_x"]), int(march["from_y"])
            to_x, to_y = int(march["to_x"]), int(march["to_y"])
            distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)
            await combat_rm.update_march_metadata(march_id, {
                "status": "returning",
                "return_time": return_time.isoformat(),
                "survived_units": {str(k): v for k, v in atk_alive.items()},
            })
            await combat_rm.add_march_return_to_queue(march_id, return_time)

        await combat_rm.update_battle_field(battle_id, "status", "finished")
        await combat_rm.remove_active_battle(battle_id)
        # 전장 내 전투였으면 전장 Set에서도 제거
        bf_id = int(state.get("bf_id", 0))
        if bf_id:
            await combat_rm.bf_remove_battle(bf_id, battle_id)

    # ─────────────────────────────────────────────
    # Rally NPC 전투 시작 (rally_attack 도착 시 TaskWorker가 호출)
    # ─────────────────────────────────────────────

    async def rally_npc_battle_start(self, march_id: int, npc_id: int, rally_id: int) -> Dict:
        """Rally attack 도착 → NPC 집결 전투 시작 (Leader 버프만 적용)"""
        battle_dm = self.db_manager.get_battle_manager()
        combat_rm = self.redis_manager.get_combat_manager()

        march = await combat_rm.get_march_metadata(march_id)
        if not march:
            return self._format(False, "행군 정보 없음")
        if march.get("status") != "marching":
            return self._format(False, "이미 처리된 행군")

        rally = await combat_rm.get_rally(rally_id)
        if not rally:
            return self._format(False, "집결 정보 없음")

        leader_no = rally["leader_no"]
        atk_units = {int(k): int(v) for k, v in march["units"].items()}

        # NPC 방어 병력
        npc_configs = GameDataManager.REQUIRE_CONFIGS.get("npc", {})
        npc_cfg = npc_configs.get(npc_id)
        if not npc_cfg:
            return self._format(False, f"NPC {npc_id} 메타데이터 없음")
        def_units = dict(npc_cfg["units"])

        # NPC alive 체크
        npc_instance = await combat_rm.get_npc(npc_id)
        if not npc_instance or not npc_instance.get("alive", True):
            await combat_rm.update_march_metadata(march_id, {"status": "returning"})
            return self._format(False, "NPC가 이미 처치된 상태")

        # Leader 영웅 계수 조회 (CSV 기반, 레벨 무관)
        hero_idx = rally.get("hero_idx")
        hero_coeffs = self._hero_coefficients(hero_idx)

        # Battle DB 생성
        result = battle_dm.create_battle({
            "march_id": march_id,
            "attacker_user_no": leader_no,
            "defender_user_no": 0,
        })
        if not result["success"]:
            return self._format(False, "전투 생성 실패")

        battle_id = result["data"]["battle_id"]
        await combat_rm.update_march_metadata(march_id, {"status": "battling", "battle_id": battle_id})
        self.db_manager.commit()

        atk_stats = self._calc_army_stats(atk_units, hero_coeffs)
        def_stats = self._calc_army_stats(def_units)

        bf_id = await combat_rm.get_user_battlefield(leader_no) or 0

        await combat_rm.set_battle_state(battle_id, {
            "battle_id": battle_id,
            "march_id": march_id,
            "rally_id": rally_id,
            "battle_type": "rally_npc",
            "npc_id": npc_id,
            "hero_idx": hero_idx,
            "def_hero_idx": None,  # NPC는 영웅 없음
            "attacker_no": leader_no,
            "defender_no": 0,
            "atk_units": atk_units,
            "def_units": def_units,
            "atk_max_hp": atk_stats["health"],
            "def_max_hp": def_stats["health"],
            "atk_hp": atk_stats["health"],
            "def_hp": def_stats["health"],
            "to_x": march.get("to_x", 0),
            "to_y": march.get("to_y", 0),
            "bf_id": bf_id,
            "round": 0,
            "atk_rage": 0,
            "def_rage": 0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "status": "active",
        })
        await combat_rm.add_active_battle(battle_id)
        if bf_id:
            await combat_rm.bf_add_battle(bf_id, battle_id)

        return self._format(True, "Rally NPC 전투 시작", {
            "battle_id": battle_id,
            "battle_type": "rally_npc",
            "rally_id": rally_id,
            "x": march.get("to_x"),
            "y": march.get("to_y"),
            "atk_user_no": leader_no,
            "atk_hero_idx": hero_idx,
            "atk_max_hp": atk_stats["health"],
            "atk_units": atk_units,
            "def_user_no": 0,
            "def_npc_id": npc_id,
            "def_max_hp": def_stats["health"],
            "def_units": def_units,
        })

    # ─────────────────────────────────────────────
    # Rally NPC 전투 종료
    # ─────────────────────────────────────────────

    async def _rally_npc_battle_end(self, battle_id: int, state: Dict, total_rounds: int,
                                     result: str, atk_alive: Dict,
                                     atk_total_loss: Dict, def_total_loss: Dict):
        """Rally NPC 전투 종료 — 유닛 분배 후 멤버별 개별 귀환 march 생성"""
        combat_rm = self.redis_manager.get_combat_manager()
        battle_dm = self.db_manager.get_battle_manager()

        leader_no = int(state["attacker_no"])
        march_id = int(state["march_id"])
        rally_id = int(state.get("rally_id", 0))
        npc_id = int(state.get("npc_id", 0))

        rally = await combat_rm.get_rally(rally_id) if rally_id else None
        members = await combat_rm.get_all_rally_members(rally_id) if rally_id else {}

        # EXP 지급 (전원 동일 — 승리 시)
        if result == "attacker_win" and state.get("hero_idx"):
            hero_idx = int(state["hero_idx"])
            npc_cfg = GameDataManager.REQUIRE_CONFIGS.get("npc", {}).get(npc_id, {})
            exp_reward = int(npc_cfg.get("exp_reward", 0))
            if exp_reward > 0:
                # Leader 영웅에게만 EXP (다른 멤버는 hero 없음)
                hero_dm = self.db_manager.get_hero_manager()
                hero_dm.add_hero_exp(leader_no, hero_idx, exp_reward)
                try:
                    await combat_rm.redis.delete(f"user_data:{leader_no}:hero")
                except Exception:
                    pass

        # NPC 처치 처리
        if result in ("attacker_win", "draw") and npc_id:
            npc_cfg = GameDataManager.REQUIRE_CONFIGS.get("npc", {}).get(npc_id, {})
            respawn_min = int(npc_cfg.get("respawn_minutes", 5))
            respawn_time = datetime.utcnow() + timedelta(minutes=respawn_min)
            npc_instance = await combat_rm.get_npc(npc_id)
            if npc_instance:
                npc_instance["alive"] = False
                npc_instance["respawn_at"] = respawn_time.isoformat()
                await combat_rm.set_npc(npc_id, npc_instance)
            await combat_rm.add_npc_respawn_to_queue(npc_id, respawn_time)

        # DB 전투 결과 저장
        battle_dm.finalize_battle(
            battle_id=battle_id,
            total_rounds=total_rounds,
            result=result,
            attacker_loss={k: v for k, v in atk_total_loss.items()},
            defender_loss={k: v for k, v in def_total_loss.items()},
            loot={},
        )
        self.db_manager.commit()

        # 유닛 분배: 생존 유닛을 원래 기여 비율대로 분배
        distributed = self._distribute_survived_units(members, atk_alive, leader_no)

        # 멤버별 개별 귀환 march 생성
        target_x = rally["target_x"] if rally else int(state.get("to_x", 0))
        target_y = rally["target_y"] if rally else int(state.get("to_y", 0))

        for member_no, member_data in members.items():
            member_survived = distributed.get(member_no, {})
            from_x = member_data.get("from_x", 0)
            from_y = member_data.get("from_y", 0)
            member_march_id = member_data.get("march_id")

            member_units_orig = {int(k): int(v) for k, v in member_data.get("units", {}).items()}

            march_manager = MarchManager(self.db_manager, self.redis_manager)
            march_speed = march_manager._calc_march_speed(member_units_orig) if member_units_orig else 10
            distance = march_manager._calc_distance(target_x, target_y, from_x, from_y)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)

            if member_march_id:
                # 기존 march metadata를 귀환용으로 업데이트
                await combat_rm.update_march_metadata(member_march_id, {
                    "status": "returning",
                    "target_type": "rally_return",
                    "from_x": target_x,
                    "from_y": target_y,
                    "to_x": from_x,
                    "to_y": from_y,
                    "return_time": return_time.isoformat(),
                    "march_speed": march_speed,
                    "survived_units": {str(k): v for k, v in member_survived.items()},
                    "units": {str(k): v for k, v in member_units_orig.items()},
                })
                await combat_rm.add_march_return_to_queue(member_march_id, return_time)
            else:
                # Leader에게 march_id가 없는 경우 (방어) — 새 march 생성
                new_march_id = await combat_rm.generate_march_id()
                return_meta = {
                    "march_id": new_march_id,
                    "user_no": member_no,
                    "target_type": "rally_return",
                    "status": "returning",
                    "units": {str(k): v for k, v in member_units_orig.items()},
                    "survived_units": {str(k): v for k, v in member_survived.items()},
                    "from_x": target_x,
                    "from_y": target_y,
                    "to_x": from_x,
                    "to_y": from_y,
                    "return_time": return_time.isoformat(),
                    "march_speed": march_speed,
                }
                await combat_rm.set_march_metadata(new_march_id, return_meta)
                await combat_rm.add_user_active_march(member_no, new_march_id)
                await combat_rm.add_march_return_to_queue(new_march_id, return_time)

        # attack march 정리
        await combat_rm.delete_march_metadata(march_id)

        # Redis 전투 상태 정리
        await combat_rm.update_battle_field(battle_id, "status", "finished")
        await combat_rm.remove_active_battle(battle_id)
        bf_id = int(state.get("bf_id", 0))
        if bf_id:
            await combat_rm.bf_remove_battle(bf_id, battle_id)

        # Rally 상태 완료
        if rally_id:
            await combat_rm.update_rally(rally_id, {"status": "done"})

    @staticmethod
    def _distribute_survived_units(members: Dict[int, Dict], atk_alive: Dict[int, int],
                                    leader_no: int = 0) -> Dict[int, Dict[int, int]]:
        """
        생존 유닛을 원래 기여 비율로 분배.
        각 유닛 타입별로 floor division, 나머지는 Leader에게.
        """
        if not members or not atk_alive:
            return {}

        member_list = list(members.keys())
        if not leader_no:
            leader_no = member_list[0]

        # 각 유닛 타입별 원래 기여량 계산
        original_by_unit = {}  # {unit_idx: {member_no: count}}
        for member_no, mdata in members.items():
            for uid_str, count in mdata.get("units", {}).items():
                uid = int(uid_str)
                if uid not in original_by_unit:
                    original_by_unit[uid] = {}
                original_by_unit[uid][member_no] = int(count)

        result = {m: {} for m in member_list}

        for uid, survived_count in atk_alive.items():
            uid = int(uid)
            if uid not in original_by_unit:
                continue
            contributors = original_by_unit[uid]
            total_original = sum(contributors.values())
            if total_original == 0:
                continue

            distributed_sum = 0
            for member_no, orig_count in contributors.items():
                share = (survived_count * orig_count) // total_original
                result[member_no][uid] = share
                distributed_sum += share

            # 나머지를 Leader에게
            remainder = survived_count - distributed_sum
            if remainder > 0:
                if leader_no in result:
                    result[leader_no][uid] = result[leader_no].get(uid, 0) + remainder
                else:
                    # 방어: leader_no가 contributors에 없는 경우 첫 번째에게
                    first_contributor = next(iter(contributors))
                    result[first_contributor][uid] = result[first_contributor].get(uid, 0) + remainder

        return result

    # ─────────────────────────────────────────────
    # 성 전투 그룹 틱 (multi-attacker snapshot)
    # ─────────────────────────────────────────────

    async def process_castle_tick(self, defender_no: int, battle_ids: List[int]) -> Dict:
        """
        동일 수비자를 공격 중인 모든 전투를 스냅샷 기반으로 1라운드 일괄 처리.

        Returns: {
            "battle_results": {battle_id: {finished, result, round, state}},
            "def_eliminated": bool,
        }
        """
        combat_rm = self.redis_manager.get_combat_manager()
        unit_configs = GameDataManager.REQUIRE_CONFIGS.get("unit", {})

        # 1. 각 battle state 로드
        states = {}
        for bid in battle_ids:
            state = await combat_rm.get_battle_state(bid)
            if state and state.get("status") == "active":
                states[bid] = state

        if not states:
            return {"battle_results": {}, "def_eliminated": False}

        num_attackers = len(states)

        # 2. 수비 스냅샷 (모든 전투가 동일한 def_units 공유)
        first_state = next(iter(states.values()))
        def_units = {int(k): int(v) for k, v in first_state.get("def_units", {}).items()}
        def_hero_idx = first_state.get("def_hero_idx")
        def_hero_coeffs = self._hero_coefficients(def_hero_idx)
        def_stats = self._calc_army_stats(def_units, def_hero_coeffs)

        # 수비 기력: 공유 (첫 번째 state에서 읽고 +20 공격 + 5×공격자수 피격)
        def_rage = int(first_state.get("def_rage", 0))
        def_rage += self.RAGE_PER_ATTACK  # 수비도 공격한다
        def_rage += self.RAGE_PER_HIT * num_attackers  # 공격자 수만큼 피격
        def_rage, def_skill_mult, _ = self._check_rage_skill(def_rage, def_hero_idx)

        # 3. 각 전투별 라운드 계산 (동일 스냅샷 기준)
        accumulated_def_loss = {}  # {uid: total_lost}
        per_battle = {}
        per_battle_atk_rage = {}  # {bid: new_atk_rage}

        for bid, state in states.items():
            atk_units = {int(k): int(v) for k, v in state.get("atk_units", {}).items()}
            hero_coeffs = self._hero_coefficients(state.get("hero_idx"))
            atk_stats = self._calc_army_stats(atk_units, hero_coeffs)

            # 공격 기력: 각 전투별 개별 관리
            atk_hero_idx = state.get("hero_idx")
            atk_rage = int(state.get("atk_rage", 0))
            atk_rage += self.RAGE_PER_ATTACK  # 공격 시 +20
            atk_rage += self.RAGE_PER_HIT     # 피격 시 +5 (수비 1명에게 맞음)
            atk_rage, atk_skill_mult, _ = self._check_rage_skill(atk_rage, atk_hero_idx)
            per_battle_atk_rage[bid] = atk_rage

            round_result = self.calculate_round(atk_stats, def_stats, atk_skill_mult, def_skill_mult)
            per_battle[bid] = round_result

            # 수비 손실 누적
            for uid, lost in round_result["def_loss"].items():
                uid = int(uid)
                accumulated_def_loss[uid] = accumulated_def_loss.get(uid, 0) + lost

        # 4. 수비 병력 일괄 업데이트 (스냅샷 - 누적 손실, 실제 보유량 이하로 cap)
        new_def_units = {}
        for uid, count in def_units.items():
            remaining = count - min(accumulated_def_loss.get(uid, 0), count)
            if remaining > 0:
                new_def_units[uid] = remaining

        def_eliminated = not new_def_units
        new_def_stats = self._calc_army_stats(new_def_units, def_hero_coeffs) if new_def_units else {"health": 0}

        # 5. 각 전투 상태 업데이트 + 종료 판정
        battle_results = {}
        attacker_lose_bids = []
        attacker_win_bids = []

        for bid, state in states.items():
            round_result = per_battle[bid]
            current_round = int(state.get("round", 0)) + 1
            hero_coeffs = self._hero_coefficients(state.get("hero_idx"))

            # 누적 손실 갱신
            atk_total_loss = state.get("atk_total_loss", {})
            def_total_loss = state.get("def_total_loss", {})
            for uid, lost in round_result["atk_loss"].items():
                key = str(uid)
                atk_total_loss[key] = int(atk_total_loss.get(key, 0)) + lost
            for uid, lost in round_result["def_loss"].items():
                key = str(uid)
                def_total_loss[key] = int(def_total_loss.get(key, 0)) + lost

            # 기여도 누적 (수비에게 준 피해의 HP 환산)
            damage_dealt = float(state.get("damage_dealt", 0))
            for uid, lost in round_result["def_loss"].items():
                cfg = unit_configs.get(int(uid), {}).get("ability", {})
                hp_per = int(cfg.get("health", 100))
                damage_dealt += lost * hp_per

            atk_alive = round_result["atk_alive"]
            atk_dead = not atk_alive
            new_atk_stats = self._calc_army_stats(atk_alive, hero_coeffs) if atk_alive else {"health": 0}

            # 상태 업데이트 (기력 포함)
            updated_state = {
                **state,
                "round": current_round,
                "atk_units": atk_alive,
                "def_units": new_def_units,
                "atk_total_loss": atk_total_loss,
                "def_total_loss": def_total_loss,
                "damage_dealt": damage_dealt,
                "atk_hp": new_atk_stats["health"],
                "def_hp": new_def_stats["health"],
                "atk_rage": per_battle_atk_rage.get(bid, 0),
                "def_rage": def_rage,
            }
            await combat_rm.set_battle_state(bid, updated_state)

            # 종료 판정
            if atk_dead and def_eliminated:
                # 상호 전멸 → draw
                attacker_lose_bids.append(bid)
                battle_results[bid] = {
                    "finished": True, "result": "draw", "round": current_round,
                    "state": updated_state,
                }
            elif atk_dead:
                # 이 공격자 패배
                attacker_lose_bids.append(bid)
                battle_results[bid] = {
                    "finished": True, "result": "defender_win", "round": current_round,
                    "state": updated_state,
                }
            elif def_eliminated:
                # 이 공격자 승리 (아래에서 일괄 처리)
                attacker_win_bids.append(bid)
                battle_results[bid] = {
                    "finished": True, "result": "attacker_win", "round": current_round,
                    "state": updated_state,
                    "atk_alive": atk_alive,
                    "damage_dealt": damage_dealt,
                }
            else:
                battle_results[bid] = {
                    "finished": False, "round": current_round, "state": updated_state,
                }

        # 6. 개별 공격자 패배 처리
        for bid in attacker_lose_bids:
            br = battle_results[bid]
            st = br["state"]
            await self._castle_attacker_end(bid, st, br["round"], br["result"])

        # 7. 수비 전멸 시 — 기여도 비율 약탈 + 전체 공격자 승리 처리
        if def_eliminated and attacker_win_bids:
            await self._castle_all_attackers_win(
                defender_no, def_units, states, battle_results, attacker_win_bids)

        return {"battle_results": battle_results, "def_eliminated": def_eliminated}

    async def _castle_attacker_end(self, battle_id: int, state: Dict,
                                    total_rounds: int, result: str):
        """개별 공격자 패배/무승부 처리 — 수비자 ready는 건드리지 않음"""
        combat_rm = self.redis_manager.get_combat_manager()
        battle_dm = self.db_manager.get_battle_manager()

        attacker_no = int(state["attacker_no"])
        defender_no = int(state["defender_no"])
        march_id = int(state["march_id"])

        # DB 전투 결과
        battle_dm.finalize_battle(
            battle_id=battle_id, total_rounds=total_rounds, result=result,
            attacker_loss=state.get("atk_total_loss", {}),
            defender_loss=state.get("def_total_loss", {}),
            loot={},
        )
        self.db_manager.commit()

        # 귀환 march (생존 유닛 = 현재 atk_units)
        march = await combat_rm.get_march_metadata(march_id)
        if march:
            march_speed = int(march.get("march_speed", 1))
            from_x, from_y = int(march["from_x"]), int(march["from_y"])
            to_x, to_y = int(march["to_x"]), int(march["to_y"])
            distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)
            atk_alive = state.get("atk_units", {})
            await combat_rm.update_march_metadata(march_id, {
                "status": "returning",
                "return_time": return_time.isoformat(),
                "survived_units": {str(k): v for k, v in atk_alive.items()},
            })
            await combat_rm.add_march_return_to_queue(march_id, return_time)

        # Redis 정리
        await combat_rm.update_battle_field(battle_id, "status", "finished")
        await combat_rm.remove_active_battle(battle_id)
        await combat_rm.remove_castle_battle(defender_no, battle_id)
        bf_id = int(state.get("bf_id", 0))
        if bf_id:
            await combat_rm.bf_remove_battle(bf_id, battle_id)

    async def _castle_all_attackers_win(self, defender_no: int, original_def_units: Dict,
                                         states: Dict, battle_results: Dict,
                                         winner_bids: List[int]):
        """수비 전멸 — 모든 생존 공격자 승리, 기여도 비율 약탈 분배"""
        combat_rm = self.redis_manager.get_combat_manager()
        battle_dm = self.db_manager.get_battle_manager()
        resource_rm = self.redis_manager.get_resource_manager()
        unit_rm = self.redis_manager.get_unit_manager()

        # 1. 총 약탈 가능 자원 (수비자 자원의 20%)
        total_loot = {}
        def_resources = await resource_rm.get_cached_all_resources(defender_no)
        if def_resources:
            for res_type in ("food", "wood", "stone", "gold"):
                amt = int(def_resources.get(res_type, 0))
                looted = int(amt * self.LOOT_RATIO)
                if looted > 0:
                    total_loot[res_type] = looted

        # 2. 기여도 계산 (damage_dealt: 수비에게 준 HP 피해 누적)
        total_damage = 0.0
        damage_per_bid = {}
        for bid in winner_bids:
            dmg = float(battle_results[bid].get("damage_dealt", 0))
            damage_per_bid[bid] = dmg
            total_damage += dmg

        # 3. 수비자 유닛 손실 적용
        #    def_units_original (ready 캐시 기준, 전투 시작 시점) 사용
        #    여러 전투 중 가장 큰 original이 실제 ready 차감 대상
        deduct_units = {}
        for bid in winner_bids:
            orig = states[bid].get("def_units_original", {})
            for uid_str, count in (orig.items() if isinstance(orig, dict) else {}):
                uid = int(uid_str)
                deduct_units[uid] = max(deduct_units.get(uid, 0), int(count))
        # 패배한 공격자 전투에서도 original 확인 (더 큰 값이 있을 수 있음)
        for bid, br in battle_results.items():
            if bid not in [b for b in winner_bids]:
                st = br.get("state", {})
                orig = st.get("def_units_original", {})
                if isinstance(orig, dict):
                    for uid_str, count in orig.items():
                        uid = int(uid_str)
                        deduct_units[uid] = max(deduct_units.get(uid, 0), int(count))

        for uid, count in deduct_units.items():
            unit_idx = int(uid)
            cached = await unit_rm.get_cached_unit(defender_no, unit_idx)
            if cached:
                cached["ready"] = max(0, int(cached.get("ready", 0)) - count)
                cached["death"] = int(cached.get("death", 0)) + count
                await unit_rm.update_cached_unit(defender_no, unit_idx, cached)

        # 4. 각 공격자별 약탈 분배 + 귀환
        for bid in winner_bids:
            br = battle_results[bid]
            state = states[bid]
            attacker_no = int(state["attacker_no"])
            march_id = int(state["march_id"])

            # 기여도 비율 약탈
            ratio = damage_per_bid.get(bid, 0) / total_damage if total_damage > 0 else 1.0 / len(winner_bids)
            battle_loot = {}
            for res_type, amt in total_loot.items():
                share = int(amt * ratio)
                if share > 0:
                    battle_loot[res_type] = share

            # 자원 이전
            for res_type, looted in battle_loot.items():
                await resource_rm.change_resource_amount(defender_no, res_type, -looted)
                await resource_rm.change_resource_amount(attacker_no, res_type, looted)

            # DB 전투 결과
            battle_dm.finalize_battle(
                battle_id=bid, total_rounds=br["round"], result="attacker_win",
                attacker_loss=br["state"].get("atk_total_loss", {}),
                defender_loss=br["state"].get("def_total_loss", {}),
                loot=battle_loot,
            )

            # 귀환 march
            march = await combat_rm.get_march_metadata(march_id)
            if march:
                march_speed = int(march.get("march_speed", 1))
                from_x, from_y = int(march["from_x"]), int(march["from_y"])
                to_x, to_y = int(march["to_x"]), int(march["to_y"])
                distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
                travel_min = distance / march_speed if march_speed > 0 else 1
                return_time = datetime.utcnow() + timedelta(minutes=travel_min)
                atk_alive = br.get("atk_alive", {})
                await combat_rm.update_march_metadata(march_id, {
                    "status": "returning",
                    "return_time": return_time.isoformat(),
                    "survived_units": {str(k): v for k, v in atk_alive.items()},
                })
                await combat_rm.add_march_return_to_queue(march_id, return_time)

            # Redis 정리
            await combat_rm.update_battle_field(bid, "status", "finished")
            await combat_rm.remove_active_battle(bid)
            await combat_rm.remove_castle_battle(defender_no, bid)
            bf_id = int(state.get("bf_id", 0))
            if bf_id:
                await combat_rm.bf_remove_battle(bf_id, bid)

        self.db_manager.commit()

    # ─────────────────────────────────────────────
    # 전투 종료 (기존 1:1 — NPC/Rally에서 사용)
    # ─────────────────────────────────────────────

    async def _battle_end(self, battle_id: int, state: Dict, total_rounds: int,
                          result: str, atk_alive: Dict, def_alive: Dict,
                          atk_total_loss: Dict, def_total_loss: Dict):
        combat_rm = self.redis_manager.get_combat_manager()
        battle_dm = self.db_manager.get_battle_manager()

        attacker_no = int(state["attacker_no"])
        defender_no = int(state["defender_no"])
        march_id = int(state["march_id"])

        # 전리품 계산 (공격자 승리 시)
        loot = {}
        if result == "attacker_win":
            resource_rm = self.redis_manager.get_resource_manager()
            def_resources = await resource_rm.get_cached_all_resources(defender_no)
            if def_resources:
                for res_type in ("food", "wood", "stone", "gold"):
                    amt = int(def_resources.get(res_type, 0))
                    looted = int(amt * self.LOOT_RATIO)
                    if looted > 0:
                        loot[res_type] = looted
                # 자원 이전 (차감 후 추가)
                for res_type, looted in loot.items():
                    await resource_rm.change_resource_amount(defender_no, res_type, -looted)
                    await resource_rm.change_resource_amount(attacker_no, res_type, looted)

        # 방어자 손실 처리 (ready에서 즉시 차감 — 방어자는 성에 있으므로 귀환 불필요)
        if def_total_loss:
            unit_rm = self.redis_manager.get_unit_manager()
            for uid_str, lost in def_total_loss.items():
                unit_idx = int(uid_str)
                cached = await unit_rm.get_cached_unit(defender_no, unit_idx)
                if cached:
                    cached["ready"] = max(0, int(cached.get("ready", 0)) - lost)
                    cached["death"] = int(cached.get("death", 0)) + lost
                    await unit_rm.update_cached_unit(defender_no, unit_idx, cached)

        # DB 전투 결과 저장
        battle_dm.finalize_battle(
            battle_id=battle_id,
            total_rounds=total_rounds,
            result=result,
            attacker_loss={k: v for k, v in atk_total_loss.items()},
            defender_loss={k: v for k, v in def_total_loss.items()},
            loot=loot,
        )
        self.db_manager.commit()

        # 귀환 큐 등록 (유닛 복구는 귀환 완료 시 TaskWorker가 처리)
        march = await combat_rm.get_march_metadata(march_id)
        if march:
            march_speed = int(march.get("march_speed", 1))
            from_x, from_y = int(march["from_x"]), int(march["from_y"])
            to_x, to_y = int(march["to_x"]), int(march["to_y"])
            distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)
            await combat_rm.update_march_metadata(march_id, {
                "status": "returning",
                "return_time": return_time.isoformat(),
                "survived_units": {str(k): v for k, v in atk_alive.items()},
            })
            await combat_rm.add_march_return_to_queue(march_id, return_time)

        # Redis 정리
        await combat_rm.update_battle_field(battle_id, "status", "finished")
        await combat_rm.remove_active_battle(battle_id)
        # 전장 내 전투였으면 전장 Set에서도 제거
        bf_id = int(state.get("bf_id", 0))
        if bf_id:
            await combat_rm.bf_remove_battle(bf_id, battle_id)

    # ─────────────────────────────────────────────
    # API 메서드
    # ─────────────────────────────────────────────

    async def battle_info(self) -> Dict:
        """전투 현황 조회 (data: battle_id)"""
        user_no = self.user_no
        battle_id = int(self.data.get("battle_id", 0))
        if not battle_id:
            return self._format(False, "battle_id는 필수입니다")

        combat_rm = self.redis_manager.get_combat_manager()
        state = await combat_rm.get_battle_state(battle_id)
        if state:
            atk = int(state.get("attacker_no", 0))
            def_ = int(state.get("defender_no", 0))
            if user_no not in (atk, def_):
                return self._format(False, "권한 없음")
            return self._format(True, "OK", state)

        # 종료된 전투는 DB에서
        battle = self.db_manager.get_battle_manager().get_battle(battle_id)
        if not battle:
            return self._format(False, "전투 없음")
        if user_no not in (battle["attacker_user_no"], battle["defender_user_no"]):
            return self._format(False, "권한 없음")
        return self._format(True, "OK", battle)

    async def battle_report(self) -> Dict:
        """전투 보고서 목록 (data: limit)"""
        user_no = self.user_no
        limit = int(self.data.get("limit", 20))
        reports = self.db_manager.get_battle_manager().get_user_battle_reports(user_no, limit)
        return self._format(True, "OK", {"reports": reports})
