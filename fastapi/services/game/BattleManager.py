import json
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager


class BattleManager:
    """
    전투 관리자

    전투 흐름:
      1. march_arrival → battle_start() 호출 (TaskWorker가 트리거)
      2. BattleWorker가 1초마다 calculate_round() 호출
      3. 한 쪽 전멸 or 50라운드 → battle_end() 호출
    """

    MAX_ROUNDS = 50
    LOOT_RATIO = 0.20    # 20%
    HERO_ATK_PER_LV = 0.05  # 레벨당 5% 공격력 보너스

    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.user_no: int = None
        self.data: dict = {}

    def _format(self, success: bool, message: str, data: Any = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    # ─────────────────────────────────────────────
    # 영웅 보너스
    # ─────────────────────────────────────────────

    def _hero_atk_multiplier(self, hero_idx: Optional[int], hero_lv: int) -> float:
        if not hero_idx:
            return 1.0
        return 1.0 + self.HERO_ATK_PER_LV * hero_lv

    # ─────────────────────────────────────────────
    # 전투력 계산
    # ─────────────────────────────────────────────

    def _calc_army_stats(self, units: Dict[int, int], hero_multiplier: float = 1.0) -> Dict:
        """
        units: {unit_idx: count}
        return: {attack, defense, health, total_hp, alive_units}
        """
        unit_configs = GameDataManager.REQUIRE_CONFIGS.get("unit", {})
        total_attack = 0
        total_defense = 0
        total_hp = 0

        for unit_idx, count in units.items():
            if count <= 0:
                continue
            cfg = unit_configs.get(unit_idx, {}).get("ability", {})
            total_attack += int(cfg.get("attack", 10)) * count
            total_defense += int(cfg.get("defense", 5)) * count
            total_hp += int(cfg.get("health", 100)) * count

        total_attack = int(total_attack * hero_multiplier)
        return {
            "attack": total_attack,
            "defense": total_defense,
            "total_hp": total_hp,
            "alive_units": {k: v for k, v in units.items() if v > 0},
        }

    # ─────────────────────────────────────────────
    # 라운드 계산 (Python 구현 - C++ 포팅 예정)
    # ─────────────────────────────────────────────

    @staticmethod
    def calculate_round(atk_stats: Dict, def_stats: Dict) -> Dict:
        """
        1라운드 전투 시뮬레이션.
        공격측/방어측이 동시에 공격, 즉시 사망 처리.

        Returns: {
          atk_dmg_dealt, atk_units_lost,
          def_dmg_dealt, def_units_lost,
          atk_alive, def_alive
        }

        TODO: C++ pybind11 포팅 후 벤치마크 비교
        """
        unit_configs = GameDataManager.REQUIRE_CONFIGS.get("unit", {})

        def apply_damage(attacker_atk: int, defender_def: int,
                         defender_units: Dict[int, int]) -> Dict[int, int]:
            """공격력으로 방어측 병력 피해 계산 (방어력 경감 후 체력 차감)"""
            net_atk = max(1, attacker_atk - defender_def)
            remaining_dmg = net_atk
            loss = {}

            # unit_idx 순서대로 처리
            for unit_idx, count in list(defender_units.items()):
                if remaining_dmg <= 0:
                    break
                cfg = unit_configs.get(unit_idx, {}).get("ability", {})
                hp_per_unit = int(cfg.get("health", 100))
                total_hp = hp_per_unit * count
                if remaining_dmg >= total_hp:
                    # 전멸
                    loss[unit_idx] = count
                    remaining_dmg -= total_hp
                else:
                    killed = remaining_dmg // hp_per_unit
                    loss[unit_idx] = killed
                    remaining_dmg = 0
            return loss

        atk_units = dict(atk_stats.get("alive_units", {}))
        def_units = dict(def_stats.get("alive_units", {}))

        # 동시 공격
        def_loss = apply_damage(atk_stats["attack"], def_stats["defense"], def_units)
        atk_loss = apply_damage(def_stats["attack"], atk_stats["defense"], atk_units)

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
        from services.system.GameDataManager import GameDataManager
        march_dm = self.db_manager.get_march_manager()
        battle_dm = self.db_manager.get_battle_manager()
        combat_rm = self.redis_manager.get_combat_manager()

        march = march_dm.get_march(march_id)
        if not march:
            return self._format(False, "행군 정보 없음")
        if march["status"] != "marching":
            return self._format(False, "이미 처리된 행군")

        attacker_no = march["user_no"]
        atk_units = march["units"]

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
            march_dm.update_march_status(march_id, "returning")
            self.db_manager.commit()
            return self._format(False, "NPC가 이미 처치된 상태")

        # 영웅 레벨 조회
        hero_lv = 0
        if march.get("hero_idx"):
            try:
                hero_key = f"user_data:{attacker_no}:hero"
                raw = await combat_rm.redis.hget(hero_key, str(march["hero_idx"]))
                if raw:
                    hero_data = json.loads(raw)
                    hero_lv = int(hero_data.get("hero_lv", 0))
            except Exception:
                pass

        # Battle DB 생성 (defender_user_no=0: NPC)
        result = battle_dm.create_battle({
            "march_id": march_id,
            "attacker_user_no": attacker_no,
            "defender_user_no": 0,
        })
        if not result["success"]:
            return self._format(False, "전투 생성 실패")

        battle_id = result["data"]["battle_id"]
        march_dm.update_march_status(march_id, "battling", battle_id=battle_id)
        self.db_manager.commit()

        hero_mult = self._hero_atk_multiplier(march.get("hero_idx"), hero_lv)
        await combat_rm.set_battle_state(battle_id, {
            "battle_id": battle_id,
            "march_id": march_id,
            "battle_type": "npc",
            "npc_id": npc_id,
            "hero_idx": march.get("hero_idx"),
            "attacker_no": attacker_no,
            "defender_no": 0,
            "atk_units": atk_units,
            "def_units": def_units,
            "hero_multiplier": hero_mult,
            "round": 0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "status": "active",
        })
        await combat_rm.add_active_battle(battle_id)

        return self._format(True, "NPC 전투 시작", {"battle_id": battle_id})

    # ─────────────────────────────────────────────
    # 전투 시작 (march 도착 시 TaskWorker가 호출)
    # ─────────────────────────────────────────────

    async def battle_start(self, march_id: int) -> Dict:
        """행군 도착 → 전투 시작"""
        march_dm = self.db_manager.get_march_manager()
        battle_dm = self.db_manager.get_battle_manager()
        combat_rm = self.redis_manager.get_combat_manager()

        march = march_dm.get_march(march_id)
        if not march:
            return self._format(False, "행군 정보 없음")
        if march["status"] != "marching":
            return self._format(False, "이미 처리된 행군")

        attacker_no = march["user_no"]
        defender_no = march["target_user_no"]
        atk_units = march["units"]  # {unit_idx: count}

        # 방어 병력: Redis 캐시에서 defender ready 병력
        unit_rm = self.redis_manager.get_unit_manager()
        def_units = {}
        cached_def = await unit_rm.get_cached_units(defender_no)
        if cached_def:
            for uid_str, udata in cached_def.items():
                ready = int(udata.get("ready", 0))
                if ready > 0:
                    def_units[int(uid_str)] = ready

        # 영웅 레벨 조회 (hero Redis 캐시에서)
        hero_lv = 0
        if march.get("hero_idx"):
            try:
                hero_key = f"user_data:{attacker_no}:hero"
                raw = await self.redis_manager.get_combat_manager().redis.hget(
                    hero_key, str(march["hero_idx"])
                )
                if raw:
                    hero_data = json.loads(raw)
                    hero_lv = int(hero_data.get("hero_lv", 0))
            except Exception:
                pass

        # 전투 DB 생성
        result = battle_dm.create_battle({
            "march_id": march_id,
            "attacker_user_no": attacker_no,
            "defender_user_no": defender_no,
        })
        if not result["success"]:
            return self._format(False, "전투 생성 실패")

        battle_id = result["data"]["battle_id"]

        # March 상태 업데이트
        march_dm.update_march_status(march_id, "battling", battle_id=battle_id)
        self.db_manager.commit()

        # Redis 전투 상태 초기화
        hero_mult = self._hero_atk_multiplier(march.get("hero_idx"), hero_lv)
        await combat_rm.set_battle_state(battle_id, {
            "battle_id": battle_id,
            "march_id": march_id,
            "attacker_no": attacker_no,
            "defender_no": defender_no,
            "atk_units": atk_units,
            "def_units": def_units,
            "hero_multiplier": hero_mult,
            "round": 0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "status": "active",
        })
        await combat_rm.add_active_battle(battle_id)

        return self._format(True, "전투 시작", {"battle_id": battle_id})

    # ─────────────────────────────────────────────
    # 전투 틱 (BattleWorker가 1초마다 호출)
    # ─────────────────────────────────────────────

    async def process_battle_tick(self, battle_id: int) -> Dict:
        """1라운드 처리"""
        combat_rm = self.redis_manager.get_combat_manager()
        state = await combat_rm.get_battle_state(battle_id)
        if not state or state.get("status") != "active":
            return self._format(False, "비활성 전투")

        current_round = int(state.get("round", 0))
        atk_units = state.get("atk_units", {})
        def_units = state.get("def_units", {})
        hero_mult = float(state.get("hero_multiplier", 1.0))

        # 정수 키 보장
        atk_units = {int(k): int(v) for k, v in atk_units.items()}
        def_units = {int(k): int(v) for k, v in def_units.items()}

        # 전투력 산출
        atk_stats = self._calc_army_stats(atk_units, hero_mult)
        def_stats = self._calc_army_stats(def_units, 1.0)

        # 라운드 계산
        round_result = self.calculate_round(atk_stats, def_stats)
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

        # 상태 업데이트
        await combat_rm.set_battle_state(battle_id, {
            **state,
            "round": new_round,
            "atk_units": round_result["atk_alive"],
            "def_units": round_result["def_alive"],
            "atk_total_loss": atk_total_loss,
            "def_total_loss": def_total_loss,
        })

        # 종료 조건 체크
        atk_dead = not round_result["atk_alive"]
        def_dead = not round_result["def_alive"]
        max_reached = new_round >= self.MAX_ROUNDS

        if atk_dead or def_dead or max_reached:
            if atk_dead and def_dead:
                result_str = "draw"
            elif def_dead:
                result_str = "attacker_win"
            elif atk_dead:
                result_str = "defender_win"
            else:
                result_str = "draw"  # 라운드 초과 → 무승부

            battle_type = state.get("battle_type", "user")
            if battle_type == "npc":
                await self._npc_battle_end(battle_id, state, new_round, result_str,
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
        march_dm = self.db_manager.get_march_manager()

        attacker_no = int(state["attacker_no"])
        march_id = int(state["march_id"])
        npc_id = int(state.get("npc_id", 0))

        # 공격자 승리 시 영웅 EXP 지급
        if result == "attacker_win" and state.get("hero_idx"):
            hero_idx = int(state["hero_idx"])
            from services.system.GameDataManager import GameDataManager
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
            from services.system.GameDataManager import GameDataManager
            npc_cfg = GameDataManager.REQUIRE_CONFIGS.get('npc', {}).get(npc_id, {})
            respawn_min = int(npc_cfg.get("respawn_minutes", 5))
            respawn_time = datetime.utcnow() + timedelta(minutes=respawn_min)
            npc_instance = await combat_rm.get_npc(npc_id)
            if npc_instance:
                npc_instance["alive"] = False
                npc_instance["respawn_at"] = respawn_time.isoformat()
                await combat_rm.set_npc(npc_id, npc_instance)
            await combat_rm.add_npc_respawn_to_queue(npc_id, respawn_time)

        # 귀환 병력 처리 (공격자 생존 병력 field→ready)
        if atk_alive:
            unit_rm = self.redis_manager.get_unit_manager()
            march = march_dm.get_march(march_id)
            original_units = march["units"] if march else {}
            for uid_str, orig_count in original_units.items():
                unit_idx = int(uid_str)
                survived = int(atk_alive.get(unit_idx, 0))
                lost = orig_count - survived
                cached = await unit_rm.get_cached_unit(attacker_no, unit_idx)
                if cached:
                    cached["field"] = max(0, int(cached.get("field", 0)) - orig_count)
                    cached["ready"] = int(cached.get("ready", 0)) + survived
                    if lost > 0:
                        cached["death"] = int(cached.get("death", 0)) + lost
                    await unit_rm.update_cached_unit(attacker_no, unit_idx, cached)

        # DB 전투 결과 저장
        battle_dm.finalize_battle(
            battle_id=battle_id,
            total_rounds=total_rounds,
            result=result,
            attacker_loss={k: v for k, v in atk_total_loss.items()},
            defender_loss={k: v for k, v in def_total_loss.items()},
            loot={},
        )

        # 귀환 큐 등록
        march = march_dm.get_march(march_id)
        if march:
            march_speed = march["march_speed"]
            from_x, from_y = march["from_x"], march["from_y"]
            to_x, to_y = march["to_x"], march["to_y"]
            distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)
            march_dm.update_march_status(march_id, "returning", return_time=return_time)
            await combat_rm.add_march_return_to_queue(march_id, return_time)
            await combat_rm.invalidate_user_marches(attacker_no)

        self.db_manager.commit()

        await combat_rm.update_battle_field(battle_id, "status", "finished")
        await combat_rm.remove_active_battle(battle_id)

    # ─────────────────────────────────────────────
    # 전투 종료
    # ─────────────────────────────────────────────

    async def _battle_end(self, battle_id: int, state: Dict, total_rounds: int,
                          result: str, atk_alive: Dict, def_alive: Dict,
                          atk_total_loss: Dict, def_total_loss: Dict):
        combat_rm = self.redis_manager.get_combat_manager()
        battle_dm = self.db_manager.get_battle_manager()
        march_dm = self.db_manager.get_march_manager()

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

        # 귀환 병력 처리 (공격자 생존 병력 field→ready)
        if atk_alive:
            unit_rm = self.redis_manager.get_unit_manager()
            march = march_dm.get_march(march_id)
            original_units = march["units"] if march else {}
            for uid_str, orig_count in original_units.items():
                unit_idx = int(uid_str)
                survived = int(atk_alive.get(unit_idx, 0))
                lost = orig_count - survived
                cached = await unit_rm.get_cached_unit(attacker_no, unit_idx)
                if cached:
                    cached["field"] = max(0, int(cached.get("field", 0)) - orig_count)
                    cached["ready"] = int(cached.get("ready", 0)) + survived
                    if lost > 0:
                        cached["death"] = int(cached.get("death", 0)) + lost
                    await unit_rm.update_cached_unit(attacker_no, unit_idx, cached)

        # 방어자 손실 처리 (ready에서 차감)
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

        # 귀환 큐 등록 (공격자 귀환)
        march = march_dm.get_march(march_id)
        if march:
            march_speed = march["march_speed"]
            from_x, from_y = march["from_x"], march["from_y"]
            to_x, to_y = march["to_x"], march["to_y"]
            distance = math.sqrt((to_x - from_x) ** 2 + (to_y - from_y) ** 2)
            travel_min = distance / march_speed if march_speed > 0 else 1
            return_time = datetime.utcnow() + timedelta(minutes=travel_min)
            march_dm.update_march_status(march_id, "returning", return_time=return_time)
            await combat_rm.add_march_return_to_queue(march_id, return_time)
            await combat_rm.invalidate_user_marches(attacker_no)

        self.db_manager.commit()

        # Redis 정리
        await combat_rm.update_battle_field(battle_id, "status", "finished")
        await combat_rm.remove_active_battle(battle_id)

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
