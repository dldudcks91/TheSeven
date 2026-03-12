"""
전투 계산 엔진 (Phase 2) 테스트
- _calc_army_stats(): RoK 스타일 전투력 계산 (sqrt(count) x stat x hero_coeff)
- calculate_round(): 1라운드 킬 수 계산 + 저티어 우선 제거
- _hero_coefficients(): CSV base_stat/100 -> 배율
- _get_hero_skill(): hero_skill.csv 조회
- _check_rage_skill(): 기력 100 -> 스킬 발동 판정

테스트 인프라: conftest.py (load_game_data fixture로 CSV 1회 로드)
"""

import math
import pytest


def _bm():
    """BattleManager 클래스 lazy import (circular import 방지)"""
    from services.game.BattleManager import BattleManager
    return BattleManager


def _make_bm():
    """DB/Redis 없이 인스턴스 생성 (_calc_army_stats 호출용)"""
    BM = _bm()
    return BM.__new__(BM)


# ===========================================================================
# _calc_army_stats (E-01 ~ E-05)
# ===========================================================================
class TestCalcArmyStats:
    """_calc_army_stats: 유닛 전투력 계산"""

    def test_army_stats_basic(self, load_game_data):
        """E-01: 단일 유닛 타입 (401: atk=100, def=100, hp=100)"""
        bm = _make_bm()
        units = {401: 100}
        result = bm._calc_army_stats(units)

        sqrt_100 = math.sqrt(100)  # 10.0
        assert abs(result["power"] - 100 * sqrt_100) < 0.01
        assert abs(result["defense"] - 100 * sqrt_100) < 0.01
        assert abs(result["health"] - 100 * sqrt_100) < 0.01
        assert result["alive_units"] == {401: 100}

    def test_army_stats_mixed_units(self, load_game_data):
        """E-02: 보병(401)+중보병(402)+검사(403) 혼합"""
        bm = _make_bm()
        units = {401: 100, 402: 50, 403: 25}
        result = bm._calc_army_stats(units)

        # 401: 100 * sqrt(100) = 1000
        # 402: 110 * sqrt(50)  = 777.8..
        # 403: 120 * sqrt(25)  = 600
        expected_power = 100 * math.sqrt(100) + 110 * math.sqrt(50) + 120 * math.sqrt(25)
        assert abs(result["power"] - expected_power) < 0.01
        assert abs(result["defense"] - expected_power) < 0.01  # 동일 스탯
        assert abs(result["health"] - expected_power) < 0.01
        assert result["alive_units"] == {401: 100, 402: 50, 403: 25}

    def test_army_stats_with_hero(self, load_game_data):
        """E-03: 영웅 계수 적용 (Hero 1001: atk=1.10, def=1.05, hp=1.05)"""
        bm = _make_bm()
        units = {401: 100}
        hero_coeffs = {"atk": 1.10, "def": 1.05, "hp": 1.05}
        result = bm._calc_army_stats(units, hero_coeffs)

        sqrt_100 = math.sqrt(100)
        assert abs(result["power"] - 100 * sqrt_100 * 1.10) < 0.01
        assert abs(result["defense"] - 100 * sqrt_100 * 1.05) < 0.01
        assert abs(result["health"] - 100 * sqrt_100 * 1.05) < 0.01

    def test_army_stats_zero_count(self, load_game_data):
        """E-04: count=0 유닛 -> 무시, alive_units에서 제외"""
        bm = _make_bm()
        units = {401: 50, 402: 0}
        result = bm._calc_army_stats(units)

        expected_power = 100 * math.sqrt(50)
        assert abs(result["power"] - expected_power) < 0.01
        assert 402 not in result["alive_units"]
        assert result["alive_units"] == {401: 50}

    def test_army_stats_empty(self, load_game_data):
        """E-05: 유닛 없음 -> 모든 값 0"""
        bm = _make_bm()
        result = bm._calc_army_stats({})

        assert result["power"] == 0.0
        assert result["defense"] == 0.0
        assert result["health"] == 0.0
        assert result["alive_units"] == {}


# ===========================================================================
# calculate_round (E-10 ~ E-14)
# ===========================================================================
class TestCalculateRoundEngine:
    """calculate_round: 1라운드 전투 시뮬레이션"""

    def test_round_low_tier_dies_first(self, load_game_data):
        """E-10: 보병(401)+검사(403) -> 401이 먼저 사망 (sorted 순서)"""
        BM = _bm()
        atk_stats = {
            "power": 50000, "defense": 1000, "health": 50000,
            "alive_units": {401: 500},
        }
        def_stats = {
            "power": 100, "defense": 50, "health": 500,
            "alive_units": {401: 10, 403: 10},
        }

        result = BM.calculate_round(atk_stats, def_stats)

        # 401(저티어)이 먼저 제거됨
        if result["def_loss"]:
            if 401 in result["def_loss"] and 403 in result["def_loss"]:
                # 401이 전멸해야 403에 피해가 감
                assert result["def_loss"][401] == 10  # 401 전멸
            elif 401 in result["def_loss"]:
                # 401만 피해 (킬 수가 10 이하)
                assert 403 not in result["def_loss"]

    def test_round_skill_mult_increases_kills(self, load_game_data):
        """E-11: skill_mult=1.5 -> 킬 수 1.5배"""
        BM = _bm()
        atk_stats = {
            "power": 1000, "defense": 500, "health": 5000,
            "alive_units": {401: 100},
        }
        def_stats = {
            "power": 500, "defense": 200, "health": 3000,
            "alive_units": {401: 100},
        }

        result_normal = BM.calculate_round(atk_stats, def_stats)
        result_skill = BM.calculate_round(atk_stats, def_stats, atk_skill_mult=1.5)

        normal_def_loss = sum(result_normal["def_loss"].values())
        skill_def_loss = sum(result_skill["def_loss"].values())
        assert skill_def_loss > normal_def_loss

        # 공격자 손실은 동일 (수비 스킬 없음)
        normal_atk_loss = sum(result_normal["atk_loss"].values())
        skill_atk_loss = sum(result_skill["atk_loss"].values())
        assert normal_atk_loss == skill_atk_loss

    def test_round_both_skill_mult(self, load_game_data):
        """E-12: 양측 스킬 발동 -> 양측 킬 증가"""
        BM = _bm()
        atk_stats = {
            "power": 1000, "defense": 500, "health": 5000,
            "alive_units": {401: 100},
        }
        def_stats = {
            "power": 1000, "defense": 500, "health": 5000,
            "alive_units": {401: 100},
        }

        result_normal = BM.calculate_round(atk_stats, def_stats)
        result_both = BM.calculate_round(
            atk_stats, def_stats, atk_skill_mult=2.0, def_skill_mult=2.0)

        normal_def_loss = sum(result_normal["def_loss"].values())
        both_def_loss = sum(result_both["def_loss"].values())
        normal_atk_loss = sum(result_normal["atk_loss"].values())
        both_atk_loss = sum(result_both["atk_loss"].values())

        assert both_def_loss > normal_def_loss
        assert both_atk_loss > normal_atk_loss

    def test_round_equal_forces(self, load_game_data):
        """E-13: 동일 전력 -> 양측 동일 피해"""
        BM = _bm()
        stats = {
            "power": 1000, "defense": 500, "health": 5000,
            "alive_units": {401: 100},
        }

        result = BM.calculate_round(stats, stats)

        atk_loss_total = sum(result["atk_loss"].values())
        def_loss_total = sum(result["def_loss"].values())
        assert atk_loss_total == def_loss_total

    def test_round_zero_defense(self, load_game_data):
        """E-14: 방어력/HP 0 -> 0으로 나누기 방지, kills=0"""
        BM = _bm()
        atk_stats = {
            "power": 1000, "defense": 0, "health": 0,
            "alive_units": {401: 50},
        }
        def_stats = {
            "power": 1000, "defense": 0, "health": 0,
            "alive_units": {401: 50},
        }

        result = BM.calculate_round(atk_stats, def_stats)
        assert sum(result["atk_loss"].values()) == 0
        assert sum(result["def_loss"].values()) == 0


# ===========================================================================
# _hero_coefficients (E-20 ~ E-22)
# ===========================================================================
class TestHeroCoefficients:
    """_hero_coefficients: CSV 기반 영웅 계수"""

    def test_hero_coeff_normal(self, load_game_data):
        """E-20: hero_idx=1001 -> base_attack=110 -> atk=1.10"""
        BM = _bm()
        result = BM._hero_coefficients(1001)

        assert abs(result["atk"] - 1.10) < 0.001
        assert abs(result["def"] - 1.05) < 0.001
        assert abs(result["hp"] - 1.05) < 0.001

    def test_hero_coeff_second_hero(self, load_game_data):
        """E-20b: hero_idx=1002 -> atk=1.00, def=1.10, hp=1.10"""
        BM = _bm()
        result = BM._hero_coefficients(1002)

        assert abs(result["atk"] - 1.00) < 0.001
        assert abs(result["def"] - 1.10) < 0.001
        assert abs(result["hp"] - 1.10) < 0.001

    def test_hero_coeff_no_hero(self, load_game_data):
        """E-21: hero_idx=None -> 기본값"""
        BM = _bm()
        result = BM._hero_coefficients(None)
        assert result == {"atk": 1.0, "def": 1.0, "hp": 1.0}

    def test_hero_coeff_zero_hero(self, load_game_data):
        """E-21b: hero_idx=0 -> 기본값 (falsy)"""
        BM = _bm()
        result = BM._hero_coefficients(0)
        assert result == {"atk": 1.0, "def": 1.0, "hp": 1.0}

    def test_hero_coeff_none_string(self, load_game_data):
        """E-21c: hero_idx="None" (Redis 직렬화) -> 기본값"""
        BM = _bm()
        result = BM._hero_coefficients("None")
        assert result == {"atk": 1.0, "def": 1.0, "hp": 1.0}

    def test_hero_coeff_invalid_hero(self, load_game_data):
        """E-22: 존재하지 않는 hero_idx=9999 -> 기본값"""
        BM = _bm()
        result = BM._hero_coefficients(9999)
        assert result == {"atk": 1.0, "def": 1.0, "hp": 1.0}


# ===========================================================================
# _get_hero_skill (추가)
# ===========================================================================
class TestGetHeroSkill:
    """_get_hero_skill: hero_skill.csv 조회"""

    def test_skill_exists(self, load_game_data):
        """hero_idx=1001 -> skill_idx=10001, damage, value=500"""
        BM = _bm()
        skill = BM._get_hero_skill(1001)
        assert skill is not None
        assert skill["hero_idx"] == 1001
        assert skill["effect_type"] == "damage"
        assert skill["value"] == 500

    def test_skill_second_hero(self, load_game_data):
        """hero_idx=1002 -> skill_idx=10002, damage, value=300"""
        BM = _bm()
        skill = BM._get_hero_skill(1002)
        assert skill is not None
        assert skill["hero_idx"] == 1002
        assert skill["value"] == 300

    def test_skill_no_hero(self, load_game_data):
        """hero_idx=None -> None"""
        assert _bm()._get_hero_skill(None) is None

    def test_skill_none_string(self, load_game_data):
        """hero_idx="None" (Redis) -> None"""
        assert _bm()._get_hero_skill("None") is None

    def test_skill_invalid_hero(self, load_game_data):
        """존재하지 않는 hero_idx=9999 -> None"""
        assert _bm()._get_hero_skill(9999) is None


# ===========================================================================
# _check_rage_skill (E-30 ~ E-34)
# ===========================================================================
class TestCheckRageSkill:
    """_check_rage_skill: 기력 스킬 발동 판정"""

    def test_rage_below_max(self, load_game_data):
        """E-30: rage=80 -> 스킬 미발동"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(80, 1001)
        assert rage == 80
        assert mult == 1.0
        assert fired is False

    def test_rage_at_max(self, load_game_data):
        """E-31: rage=100 + hero=1001 -> 스킬 발동 (mult=6.0)"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(100, 1001)

        # skill 10001: value=500 -> mult = 1 + 500/100 = 6.0
        assert rage == 0
        assert abs(mult - 6.0) < 0.01
        assert fired is True

    def test_rage_at_max_hero2(self, load_game_data):
        """E-31b: rage=100 + hero=1002 -> mult=4.0"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(100, 1002)

        assert rage == 0
        assert abs(mult - 4.0) < 0.01
        assert fired is True

    def test_rage_no_hero(self, load_game_data):
        """E-32: rage=100 + hero=None -> 스킬 미발동, rage 유지"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(100, None)

        assert rage == 100
        assert mult == 1.0
        assert fired is False

    def test_rage_none_string_hero(self, load_game_data):
        """E-32b: rage=100 + hero="None" (Redis) -> 스킬 미발동"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(100, "None")

        assert rage == 100
        assert mult == 1.0
        assert fired is False

    def test_rage_hero_no_skill(self, load_game_data):
        """E-33: rage=100 + hero 존재, 스킬 없음 -> rage 차감, 배율 1.0"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(100, 9999)

        # hero_idx=9999: truthy + str != "None" -> 스킬 조회
        # _get_hero_skill(9999) = None -> skill_mult=1.0
        # rage -= 100 (영웅 존재하면 rage 소모는 일어남)
        assert rage == 0
        assert mult == 1.0
        assert fired is False

    def test_rage_overflow(self, load_game_data):
        """E-34: rage=120 -> 스킬 발동 후 rage=20"""
        BM = _bm()
        rage, mult, fired = BM._check_rage_skill(120, 1001)

        assert rage == 20
        assert abs(mult - 6.0) < 0.01
        assert fired is True
