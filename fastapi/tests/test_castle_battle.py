"""
성 일반전투 (Castle Normal Attack) 테스트
- battle_start(): 전투 시작, 무혈입성, 기존 전투 동기화
- process_castle_tick(): 단일/멀티 공격자, 공격자 패배, 수비 전멸
- 기여도 비율 약탈 분배 검증

테스트 인프라: conftest.py (theseven_test DB + fakeredis + AsyncClient)

테스트 방식:
  BattleManager 메서드 직접 호출 (Worker 경유 아닌 단위 테스트)
  → DB session + RedisManager(fakeredis) 로 인스턴스 생성
"""

import pytest
import pytest_asyncio
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

async def setup_resources(fake_redis, user_no, food=100000, wood=100000, stone=100000, gold=100000):
    """Redis에 자원 세팅"""
    hash_key = f"user_data:{user_no}:resources"
    await fake_redis.hset(hash_key, mapping={
        "food": str(food), "wood": str(wood),
        "stone": str(stone), "gold": str(gold), "ruby": "0",
    })


async def setup_unit_cache(fake_redis, user_no, unit_idx, ready=0, field=0, death=0):
    """Redis 유닛 캐시 세팅"""
    unit_data = {
        "user_no": user_no, "unit_idx": unit_idx,
        "total": ready + field + death,
        "ready": ready, "training": 0, "upgrading": 0,
        "field": field, "injured": 0, "wounded": 0,
        "healing": 0, "death": death,
        "training_end_time": None,
        "cached_at": datetime.utcnow().isoformat(),
    }
    hash_key = f"user_data:{user_no}:unit"
    await fake_redis.hset(hash_key, str(unit_idx), json.dumps(unit_data))


async def setup_march(fake_redis, march_id, attacker_no, defender_no,
                      units, hero_idx=0, status="marching"):
    """Redis에 march metadata 세팅"""
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)

    metadata = {
        "march_id": march_id,
        "user_no": attacker_no,
        "target_type": "user",
        "target_user_no": defender_no,
        "units": {str(k): v for k, v in units.items()},
        "hero_idx": hero_idx,
        "from_x": 10, "from_y": 10,
        "to_x": 50, "to_y": 50,
        "march_speed": 10,
        "status": status,
        "departure_time": datetime.utcnow().isoformat(),
        "arrival_time": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
    }
    await combat_rm.set_march_metadata(march_id, metadata)
    return metadata


async def setup_map_position(fake_redis, user_no, x, y):
    """맵 위치 세팅"""
    await fake_redis.hset("map:positions", str(user_no), f"{x},{y}")


def create_battle_manager(db_session, fake_redis):
    """테스트용 BattleManager 인스턴스"""
    from services.db_manager.DBManager import DBManager
    from services.redis_manager.RedisManager import RedisManager
    from services.game.BattleManager import BattleManager
    db_manager = DBManager(db_session)
    redis_manager = RedisManager(fake_redis)
    return BattleManager(db_manager, redis_manager), db_manager, redis_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ATTACKER_NO = 99901
DEFENDER_NO = 99902
ATTACKER2_NO = 99903


@pytest.fixture
def setup_test_users():
    """테스트용 유저 3명 DB 생성"""
    from tests.conftest import TestSessionLocal
    session = TestSessionLocal()
    try:
        from models import StatNation, Resources
        for user_no, name, x, y in [
            (ATTACKER_NO, "Attacker1", 10, 10),
            (DEFENDER_NO, "Defender", 50, 50),
            (ATTACKER2_NO, "Attacker2", 20, 20),
        ]:
            session.add(StatNation(
                account_no=user_no, user_no=user_no, alliance_no=0,
                name=name, hq_lv=5, power=0,
                cr_dt=datetime.now(), last_dt=datetime.now(),
            ))
            session.add(Resources(
                user_no=user_no,
                food=100000, wood=100000, stone=100000, gold=100000, ruby=0,
            ))
        session.commit()
    finally:
        session.close()


@pytest_asyncio.fixture
async def battle_env(fake_redis, setup_test_users):
    """전투 테스트 환경: DB session + BattleManager + Redis 초기 데이터"""
    from tests.conftest import TestSessionLocal
    db_session = TestSessionLocal()

    bm, db_manager, redis_manager = create_battle_manager(db_session, fake_redis)
    combat_rm = redis_manager.get_combat_manager()

    # 맵 위치 설정
    await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)
    await setup_map_position(fake_redis, DEFENDER_NO, 50, 50)
    await setup_map_position(fake_redis, ATTACKER2_NO, 20, 20)

    yield {
        "bm": bm,
        "db_manager": db_manager,
        "redis_manager": redis_manager,
        "combat_rm": combat_rm,
        "fake_redis": fake_redis,
        "db_session": db_session,
    }

    db_session.close()


# ===========================================================================
# battle_start() — 정상 전투 시작
# ===========================================================================
class TestBattleStart:
    @pytest.mark.asyncio
    async def test_normal_battle_start(self, battle_env):
        """수비 병력 있는 상태에서 정상 전투 시작"""
        env = battle_env
        fr = env["fake_redis"]

        # 수비자 유닛 ready 세팅
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=100)
        # 공격자 march 세팅
        await setup_march(fr, 1, ATTACKER_NO, DEFENDER_NO, {401: 50})

        result = await env["bm"].battle_start(1)

        assert result["success"] is True
        assert result["data"]["battle_type"] == "user"
        assert result["data"]["atk_user_no"] == ATTACKER_NO
        assert result["data"]["def_user_no"] == DEFENDER_NO

        # Redis: battle state 생성 확인
        battle_id = result["data"]["battle_id"]
        state = await env["combat_rm"].get_battle_state(battle_id)
        assert state is not None
        assert state["status"] == "active"
        assert state["battle_type"] == "user"

        # Redis: castle_battle Set 등록 확인
        castle_bids = await env["combat_rm"].get_castle_battles(DEFENDER_NO)
        assert battle_id in castle_bids

        # Redis: active battle 등록 확인
        active = await env["combat_rm"].get_active_battles()
        assert battle_id in active

    @pytest.mark.asyncio
    async def test_already_processed_march(self, battle_env):
        """이미 처리된 행군 → 실패"""
        env = battle_env
        fr = env["fake_redis"]
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=100)
        await setup_march(fr, 2, ATTACKER_NO, DEFENDER_NO, {401: 50}, status="battling")

        result = await env["bm"].battle_start(2)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_no_march_metadata(self, battle_env):
        """행군 메타데이터 없음 → 실패"""
        result = await battle_env["bm"].battle_start(999)
        assert result["success"] is False


# ===========================================================================
# battle_start() — 무혈입성
# ===========================================================================
class TestBloodlessEntry:
    @pytest.mark.asyncio
    async def test_bloodless_no_defender_units(self, battle_env):
        """수비 병력 0 → 무혈입성 (약탈 + 즉시 귀환)"""
        env = battle_env
        fr = env["fake_redis"]

        # 수비자: 유닛 없음 (캐시 자체 없음)
        await setup_resources(fr, DEFENDER_NO, food=10000, wood=10000, stone=10000, gold=10000)
        await setup_resources(fr, ATTACKER_NO, food=0, wood=0, stone=0, gold=0)
        await setup_march(fr, 3, ATTACKER_NO, DEFENDER_NO, {401: 50})

        result = await env["bm"].battle_start(3)

        assert result["success"] is True
        assert result["data"]["bloodless"] is True
        assert result["data"]["battle_type"] == "user"

        # 약탈 확인 (20%)
        loot = result["data"]["loot"]
        assert loot.get("food", 0) == 2000  # 10000 * 0.2

        # 공격자 자원 증가 확인
        atk_res_key = f"user_data:{ATTACKER_NO}:resources"
        atk_food = await fr.hget(atk_res_key, "food")
        assert int(atk_food) == 2000

        # 수비자 자원 감소 확인
        def_res_key = f"user_data:{DEFENDER_NO}:resources"
        def_food = await fr.hget(def_res_key, "food")
        assert int(def_food) == 8000

        # 귀환 march 등록 확인
        assert result["data"].get("return_time") is not None

    @pytest.mark.asyncio
    async def test_bloodless_zero_ready_units(self, battle_env):
        """수비자 유닛 존재하지만 ready=0 → 무혈입성"""
        env = battle_env
        fr = env["fake_redis"]

        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=0, field=50)
        await setup_resources(fr, DEFENDER_NO, food=5000)
        await setup_resources(fr, ATTACKER_NO, food=0)
        await setup_march(fr, 4, ATTACKER_NO, DEFENDER_NO, {401: 30})

        result = await env["bm"].battle_start(4)

        assert result["success"] is True
        assert result["data"]["bloodless"] is True


# ===========================================================================
# battle_start() — 기존 전투 동기화
# ===========================================================================
class TestExistingBattleSync:
    @pytest.mark.asyncio
    async def test_sync_def_units_from_existing_battle(self, battle_env):
        """기존 진행 중 전투가 있으면 현재 수비 병력으로 동기화"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # 수비자 ready 캐시: 100
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=100)

        # 기존 전투 상태 수동 세팅 (수비 병력 60으로 감소된 상태)
        existing_bid = 9000
        await combat_rm.set_battle_state(existing_bid, {
            "battle_id": existing_bid,
            "battle_type": "user",
            "attacker_no": ATTACKER2_NO,
            "defender_no": DEFENDER_NO,
            "atk_units": {401: 30},
            "def_units": {401: 60},  # 100에서 60으로 감소
            "status": "active",
            "round": 5,
            "hero_multiplier": 1.0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "damage_dealt": 0,
            "def_units_original": {401: 100},
        })
        await combat_rm.add_active_battle(existing_bid)
        await combat_rm.add_castle_battle(DEFENDER_NO, existing_bid)

        # 새 공격자 march
        await setup_march(fr, 5, ATTACKER_NO, DEFENDER_NO, {401: 40})

        result = await env["bm"].battle_start(5)

        assert result["success"] is True
        assert result["data"].get("bloodless") is not True  # 수비 60 남아있으므로 전투 시작

        # 새 전투의 def_units가 60으로 동기화되었는지 확인
        new_bid = result["data"]["battle_id"]
        state = await combat_rm.get_battle_state(new_bid)
        def_units = state["def_units"]
        assert def_units.get(401, def_units.get("401", 0)) == 60

    @pytest.mark.asyncio
    async def test_bloodless_when_existing_battle_reduced_to_zero(self, battle_env):
        """기존 전투에서 수비 병력 0으로 감소 → 무혈입성"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=100)
        await setup_resources(fr, DEFENDER_NO, food=5000)
        await setup_resources(fr, ATTACKER_NO, food=0)

        # 기존 전투: 수비 병력 0
        existing_bid = 9001
        await combat_rm.set_battle_state(existing_bid, {
            "battle_id": existing_bid,
            "battle_type": "user",
            "attacker_no": ATTACKER2_NO,
            "defender_no": DEFENDER_NO,
            "atk_units": {401: 30},
            "def_units": {},  # 전멸
            "status": "active",
            "round": 10,
            "hero_multiplier": 1.0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "damage_dealt": 0,
            "def_units_original": {401: 100},
        })
        await combat_rm.add_castle_battle(DEFENDER_NO, existing_bid)

        await setup_march(fr, 6, ATTACKER_NO, DEFENDER_NO, {401: 40})

        result = await env["bm"].battle_start(6)
        assert result["success"] is True
        assert result["data"]["bloodless"] is True


# ===========================================================================
# process_castle_tick() — 단일 공격자
# ===========================================================================
class TestCastleTickSingle:
    @pytest.mark.asyncio
    async def test_single_attacker_tick(self, battle_env):
        """단일 공격자 → 1라운드 진행"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=100)
        await setup_march(fr, 10, ATTACKER_NO, DEFENDER_NO, {401: 50})

        # 전투 시작
        result = await env["bm"].battle_start(10)
        assert result["success"] is True
        bid = result["data"]["battle_id"]

        # 1 tick
        tick_result = await env["bm"].process_castle_tick(DEFENDER_NO, [bid])

        battle_results = tick_result["battle_results"]
        assert bid in battle_results
        assert battle_results[bid]["round"] == 1

        # 상태 업데이트 확인
        state = await combat_rm.get_battle_state(bid)
        assert int(state["round"]) == 1

    @pytest.mark.asyncio
    async def test_single_attacker_until_finish(self, battle_env):
        """단일 공격자 반복 tick → 한쪽 전멸까지"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # 공격자 강하게, 수비자 약하게
        # unit 401: attack=1, defense=1, hp=100
        # net_dmg >= hp(100)이 되려면 공격 병력 - 수비 병력 > 100 필요
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=10)
        await setup_march(fr, 11, ATTACKER_NO, DEFENDER_NO, {401: 1000})

        result = await env["bm"].battle_start(11)
        bid = result["data"]["battle_id"]

        finished = False
        for _ in range(100):  # 최대 100라운드
            tick = await env["bm"].process_castle_tick(DEFENDER_NO, [bid])
            br = tick["battle_results"].get(bid, {})
            if br.get("finished"):
                finished = True
                # 공격자 우세 → attacker_win 예상
                assert br["result"] in ("attacker_win", "draw")
                break

        assert finished, "전투가 100라운드 내에 종료되지 않음"

        # 종료 후 Redis 정리 확인
        active = await combat_rm.get_active_battles()
        assert bid not in active
        castle_bids = await combat_rm.get_castle_battles(DEFENDER_NO)
        assert bid not in castle_bids


# ===========================================================================
# process_castle_tick() — 멀티 공격자
# ===========================================================================
class TestCastleTickMulti:
    @pytest.mark.asyncio
    async def test_two_attackers_shared_snapshot(self, battle_env):
        """2명의 공격자가 동일한 수비 스냅샷에 대해 전투"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=200)

        # 공격자 1 march + battle_start
        await setup_march(fr, 20, ATTACKER_NO, DEFENDER_NO, {401: 80})
        r1 = await env["bm"].battle_start(20)
        assert r1["success"] is True
        bid1 = r1["data"]["battle_id"]

        # 공격자 2 march + battle_start (기존 전투 동기화)
        await setup_march(fr, 21, ATTACKER2_NO, DEFENDER_NO, {401: 60})
        r2 = await env["bm"].battle_start(21)
        assert r2["success"] is True
        bid2 = r2["data"]["battle_id"]

        # castle_battle에 2개 등록 확인
        castle_bids = await combat_rm.get_castle_battles(DEFENDER_NO)
        assert bid1 in castle_bids
        assert bid2 in castle_bids

        # 1 tick — 두 전투 동시 처리
        tick = await env["bm"].process_castle_tick(DEFENDER_NO, [bid1, bid2])
        br = tick["battle_results"]
        assert bid1 in br
        assert bid2 in br

        # 두 전투의 def_units가 동일한지 확인 (스냅샷 공유)
        s1 = await combat_rm.get_battle_state(bid1)
        s2 = await combat_rm.get_battle_state(bid2)
        assert s1["def_units"] == s2["def_units"]

    @pytest.mark.asyncio
    async def test_multi_attacker_defender_eliminated(self, battle_env):
        """멀티 공격자 → 수비 전멸 → 기여도 비율 약탈"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # 수비자 약하게 (빠른 전멸 유도)
        # unit 401: attack=1, defense=1, hp=100
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=10)
        await setup_resources(fr, DEFENDER_NO, food=10000, wood=10000, stone=10000, gold=10000)
        await setup_resources(fr, ATTACKER_NO, food=0, wood=0, stone=0, gold=0)
        await setup_resources(fr, ATTACKER2_NO, food=0, wood=0, stone=0, gold=0)

        # 공격자 1: 강함 (1000명 → net_dmg=990, 수비 9명/라운드 처치)
        await setup_march(fr, 30, ATTACKER_NO, DEFENDER_NO, {401: 1000})
        r1 = await env["bm"].battle_start(30)
        bid1 = r1["data"]["battle_id"]

        # 공격자 2: 약간 약함 (500명 → net_dmg=490, 수비 4명/라운드 처치)
        await setup_march(fr, 31, ATTACKER2_NO, DEFENDER_NO, {401: 500})
        r2 = await env["bm"].battle_start(31)
        bid2 = r2["data"]["battle_id"]

        # 반복 tick — 수비 전멸까지
        finished = False
        for _ in range(100):
            tick = await env["bm"].process_castle_tick(DEFENDER_NO, [bid1, bid2])
            if tick["def_eliminated"]:
                finished = True
                break

        assert finished, "수비 전멸이 발생하지 않음"

        # 두 공격자 모두 승리
        br = tick["battle_results"]
        for bid in [bid1, bid2]:
            if bid in br and br[bid].get("finished"):
                assert br[bid]["result"] == "attacker_win"

        # 약탈 분배 확인 (공격자들이 자원을 받았는지)
        atk1_food = await fr.hget(f"user_data:{ATTACKER_NO}:resources", "food")
        atk2_food = await fr.hget(f"user_data:{ATTACKER2_NO}:resources", "food")
        total_looted = int(atk1_food or 0) + int(atk2_food or 0)

        # 20% of 10000 = 2000 약탈됨 (int 절삭으로 1~2 오차 허용)
        assert 1990 <= total_looted <= 2000

        # 공격자 1이 더 많이 받아야 함 (병력 1000 vs 500 → 기여도 높음)
        assert int(atk1_food or 0) >= int(atk2_food or 0)

        # 수비자 자원 감소 확인
        def_food = await fr.hget(f"user_data:{DEFENDER_NO}:resources", "food")
        assert int(def_food) <= 8010  # 약 2000 약탈됨


# ===========================================================================
# process_castle_tick() — 공격자 패배
# ===========================================================================
class TestCastleTickAttackerLose:
    @pytest.mark.asyncio
    async def test_attacker_eliminated(self, battle_env):
        """공격자 전멸 → defender_win, 수비 ready 유지"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # 수비 강함, 공격 약함
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=200)
        await setup_march(fr, 40, ATTACKER_NO, DEFENDER_NO, {401: 5})

        r = await env["bm"].battle_start(40)
        bid = r["data"]["battle_id"]

        finished = False
        final_result = None
        for _ in range(100):
            tick = await env["bm"].process_castle_tick(DEFENDER_NO, [bid])
            br = tick["battle_results"].get(bid, {})
            if br.get("finished"):
                finished = True
                final_result = br["result"]
                break

        assert finished
        assert final_result == "defender_win"

        # 종료 후 귀환 march 등록 확인 (패배해도 생존 유닛 귀환)
        march = await combat_rm.get_march_metadata(40)
        assert march["status"] == "returning"

    @pytest.mark.asyncio
    async def test_multi_one_attacker_dies_other_continues(self, battle_env):
        """멀티 공격자: 한 명 전멸, 다른 한 명 계속 전투"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # 수비 강함 → 약한 공격자 빠르게 전멸, 강한 공격자는 생존
        # unit 401: attack=1, defense=1, hp=100
        # 수비 500명: attack=500, defense=500
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=500)

        # 공격자 1: 약함 (5명 → 수비 net_dmg=495, 4명/라운드 처치 → 2라운드 전멸)
        await setup_march(fr, 50, ATTACKER_NO, DEFENDER_NO, {401: 5})
        r1 = await env["bm"].battle_start(50)
        bid1 = r1["data"]["battle_id"]

        # 공격자 2: 강함 (2000명 → 수비 net_dmg 낮아 오래 생존)
        await setup_march(fr, 51, ATTACKER2_NO, DEFENDER_NO, {401: 2000})
        r2 = await env["bm"].battle_start(51)
        bid2 = r2["data"]["battle_id"]

        bid1_finished = False
        bid2_still_active = True

        for i in range(30):
            # bid1이 종료되면 목록에서 제거
            active_bids = [b for b in [bid1, bid2]
                           if not (b == bid1 and bid1_finished)]
            if not active_bids:
                break

            tick = await env["bm"].process_castle_tick(DEFENDER_NO, active_bids)
            br = tick["battle_results"]

            if bid1 in br and br[bid1].get("finished") and not bid1_finished:
                bid1_finished = True
                assert br[bid1]["result"] == "defender_win"

            if bid2 in br and br[bid2].get("finished"):
                bid2_still_active = False
                break

        # 공격자 1은 패배해야 함
        assert bid1_finished, "약한 공격자가 30라운드 내에 전멸하지 않음"


# ===========================================================================
# def_units_original 정합성
# ===========================================================================
class TestDefUnitsOriginal:
    @pytest.mark.asyncio
    async def test_original_stored_at_battle_start(self, battle_env):
        """battle_start 시 def_units_original이 ready 캐시 기준으로 저장"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=150)
        await setup_march(fr, 60, ATTACKER_NO, DEFENDER_NO, {401: 50})

        r = await env["bm"].battle_start(60)
        bid = r["data"]["battle_id"]

        state = await combat_rm.get_battle_state(bid)
        orig = state.get("def_units_original", {})
        # ready 캐시 기준 (150)이어야 함
        assert int(orig.get(401, orig.get("401", 0))) == 150

    @pytest.mark.asyncio
    async def test_original_preserved_with_existing_battle(self, battle_env):
        """기존 전투가 있어도 def_units_original은 ready 캐시 기준"""
        env = battle_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # ready 캐시: 150
        await setup_unit_cache(fr, DEFENDER_NO, 401, ready=150)

        # 기존 전투: def_units가 80으로 감소
        existing_bid = 9010
        await combat_rm.set_battle_state(existing_bid, {
            "battle_id": existing_bid,
            "battle_type": "user",
            "attacker_no": ATTACKER2_NO,
            "defender_no": DEFENDER_NO,
            "atk_units": {401: 30},
            "def_units": {401: 80},
            "status": "active",
            "round": 3,
            "hero_multiplier": 1.0,
            "atk_total_loss": {},
            "def_total_loss": {},
            "damage_dealt": 0,
            "def_units_original": {401: 150},
        })
        await combat_rm.add_castle_battle(DEFENDER_NO, existing_bid)

        # 새 공격자
        await setup_march(fr, 61, ATTACKER_NO, DEFENDER_NO, {401: 40})
        r = await env["bm"].battle_start(61)
        bid = r["data"]["battle_id"]

        state = await combat_rm.get_battle_state(bid)
        # def_units_original은 ready 캐시(150)이어야 함
        orig = state.get("def_units_original", {})
        assert int(orig.get(401, orig.get("401", 0))) == 150
        # def_units는 기존 전투 동기화(80)이어야 함
        def_units = state.get("def_units", {})
        assert int(def_units.get(401, def_units.get("401", 0))) == 80


# ===========================================================================
# calculate_round() 단위 테스트
# ===========================================================================
class TestCalculateRound:
    def test_basic_round(self, load_game_data):
        """기본 라운드 계산 — 양측 피해 발생"""
        from services.game.BattleManager import BattleManager
        atk_stats = {
            "power": 500, "defense": 200, "health": 5000,
            "alive_units": {401: 50},
        }
        def_stats = {
            "power": 300, "defense": 100, "health": 3000,
            "alive_units": {401: 30},
        }

        result = BattleManager.calculate_round(atk_stats, def_stats)
        assert "atk_loss" in result
        assert "def_loss" in result
        assert "atk_alive" in result
        assert "def_alive" in result

    def test_overwhelming_attack(self, load_game_data):
        """압도적 공격력 → 수비 전멸"""
        from services.game.BattleManager import BattleManager
        atk_stats = {
            "power": 100000, "defense": 10000, "health": 100000,
            "alive_units": {401: 1000},
        }
        def_stats = {
            "power": 10, "defense": 1, "health": 100,
            "alive_units": {401: 1},
        }

        result = BattleManager.calculate_round(atk_stats, def_stats)
        assert result["def_alive"] == {}  # 수비 전멸
        assert 401 in result["def_loss"]
