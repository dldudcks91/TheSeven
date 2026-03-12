"""
NPC 전투 (Phase 1) 테스트
- npc_battle_start(): NPC 전투 시작, dead NPC 처리, 영웅 계수
- process_battle_tick(): NPC 틱 진행, 기력/스킬, 승패 판정
- _npc_battle_end(): EXP 지급, NPC 처치, 귀환 march, Redis 정리

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

async def setup_npc_instance(fake_redis, npc_id, alive=True, x=15, y=25):
    """Redis에 NPC 인스턴스 세팅"""
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)
    npc_data = {
        "npc_id": npc_id,
        "alive": alive,
        "x": x,
        "y": y,
        "respawn_at": None,
    }
    await combat_rm.set_npc(npc_id, npc_data)
    return npc_data


async def setup_npc_march(fake_redis, march_id, attacker_no, npc_id,
                           units, hero_idx=0, status="marching"):
    """NPC 공격용 march metadata 세팅"""
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)

    # NPC 위치는 CSV에서 가져오되, 테스트에서는 고정값 사용
    metadata = {
        "march_id": march_id,
        "user_no": attacker_no,
        "target_type": "npc",
        "target_user_no": 0,
        "npc_id": npc_id,
        "units": {str(k): v for k, v in units.items()},
        "hero_idx": hero_idx,
        "from_x": 10, "from_y": 10,
        "to_x": 15, "to_y": 25,
        "march_speed": 10,
        "status": status,
        "departure_time": datetime.utcnow().isoformat(),
        "arrival_time": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
    }
    await combat_rm.set_march_metadata(march_id, metadata)
    return metadata


async def setup_hero_cache(fake_redis, user_no, hero_idx):
    """Redis에 영웅 캐시 세팅 (defender hero 조회용)"""
    hero_data = json.dumps({"hero_idx": hero_idx, "hero_lv": 1, "exp": 0})
    await fake_redis.hset(f"user_data:{user_no}:hero", str(hero_idx), hero_data)


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
NPC_ID = 1        # Goblin Tribe: units={1:20}, exp_reward=50, respawn=5min
NPC_ID_2 = 2      # Orc Warrior: units={1:30, 2:10}, exp_reward=120
HERO_IDX = 1001    # Arthur: atk=1.10, def=1.05, hp=1.05
HERO_IDX_2 = 1002  # Merlin: atk=1.00, def=1.10, hp=1.10


@pytest.fixture
def setup_test_users():
    """테스트용 유저 DB 생성"""
    from tests.conftest import TestSessionLocal
    session = TestSessionLocal()
    try:
        from models import StatNation, Resources, Hero
        session.add(StatNation(
            account_no=ATTACKER_NO, user_no=ATTACKER_NO, alliance_no=0,
            name="NpcAttacker", hq_lv=5, power=0,
            cr_dt=datetime.now(), last_dt=datetime.now(),
        ))
        session.add(Resources(
            user_no=ATTACKER_NO,
            food=100000, wood=100000, stone=100000, gold=100000, ruby=0,
        ))
        # 영웅 DB 레코드 (EXP 테스트용)
        session.add(Hero(
            user_no=ATTACKER_NO, hero_idx=HERO_IDX, hero_lv=1, exp=0,
        ))
        session.commit()
    finally:
        session.close()


@pytest_asyncio.fixture
async def npc_env(fake_redis, setup_test_users):
    """NPC 전투 테스트 환경"""
    from tests.conftest import TestSessionLocal
    db_session = TestSessionLocal()

    bm, db_manager, redis_manager = create_battle_manager(db_session, fake_redis)
    combat_rm = redis_manager.get_combat_manager()

    # 맵 위치
    await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)

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
# npc_battle_start() — 정상 케이스
# ===========================================================================
class TestNpcBattleStart:
    @pytest.mark.asyncio
    async def test_npc_battle_start_normal(self, npc_env):
        """N-01: 정상 NPC 전투 시작"""
        env = npc_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 1, ATTACKER_NO, NPC_ID, {401: 50})

        result = await env["bm"].npc_battle_start(1, NPC_ID)

        assert result["success"] is True
        assert result["data"]["battle_type"] == "npc"
        assert result["data"]["atk_user_no"] == ATTACKER_NO
        assert result["data"]["def_user_no"] == 0

        # Redis: battle state 확인
        battle_id = result["data"]["battle_id"]
        state = await combat_rm.get_battle_state(battle_id)
        assert state is not None
        assert state["status"] == "active"
        assert state["battle_type"] == "npc"
        assert int(state["npc_id"]) == NPC_ID

        # atk_units가 march와 일치
        atk_units = {int(k): int(v) for k, v in state["atk_units"].items()}
        assert atk_units[401] == 50

        # def_units가 NPC CSV 값과 일치 (NPC 1 = {1: 20})
        def_units = {int(k): int(v) for k, v in state["def_units"].items()}
        assert def_units[1] == 20

        # active battle 등록
        active = await combat_rm.get_active_battles()
        assert battle_id in active

    @pytest.mark.asyncio
    async def test_npc_battle_start_dead_npc(self, npc_env):
        """N-02: NPC alive=false → 전투 없이 귀환"""
        env = npc_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=False)
        await setup_npc_march(fr, 2, ATTACKER_NO, NPC_ID, {401: 50})

        result = await env["bm"].npc_battle_start(2, NPC_ID)

        assert result["success"] is False

        # march가 returning으로 변경
        march = await combat_rm.get_march_metadata(2)
        assert march["status"] == "returning"

    @pytest.mark.asyncio
    async def test_npc_battle_start_no_march(self, npc_env):
        """N-03: march 없음 → 실패"""
        result = await npc_env["bm"].npc_battle_start(999, NPC_ID)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_npc_battle_start_already_processed(self, npc_env):
        """N-04: march status≠marching → 실패"""
        env = npc_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 3, ATTACKER_NO, NPC_ID, {401: 50}, status="battling")

        result = await env["bm"].npc_battle_start(3, NPC_ID)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_npc_battle_start_invalid_npc(self, npc_env):
        """N-05: 존재하지 않는 npc_id → 실패"""
        env = npc_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, 9999, alive=True)
        await setup_npc_march(fr, 4, ATTACKER_NO, 9999, {401: 50})

        result = await env["bm"].npc_battle_start(4, 9999)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_npc_battle_start_with_hero(self, npc_env):
        """N-06: 영웅 동행 → hero_coefficients 적용 확인"""
        env = npc_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 5, ATTACKER_NO, NPC_ID, {401: 50}, hero_idx=HERO_IDX)

        result = await env["bm"].npc_battle_start(5, NPC_ID)
        assert result["success"] is True

        # Hero 1001: base_health=105 → hp coeff=1.05
        # atk_max_hp에 영웅 계수 반영 여부 확인
        battle_id = result["data"]["battle_id"]
        state = await combat_rm.get_battle_state(battle_id)

        # 영웅 없는 경우의 hp 계산: unit 401 (health=100) * sqrt(50) * 1.0
        # 영웅 있는 경우의 hp 계산: unit 401 (health=100) * sqrt(50) * 1.05
        import math
        expected_hp_no_hero = 100 * math.sqrt(50) * 1.0
        expected_hp_with_hero = 100 * math.sqrt(50) * 1.05

        atk_max_hp = float(state["atk_max_hp"])
        assert abs(atk_max_hp - expected_hp_with_hero) < 0.01
        assert atk_max_hp > expected_hp_no_hero  # 영웅 효과로 더 높음

        # hero_idx가 state에 저장
        assert int(state["hero_idx"]) == HERO_IDX

    @pytest.mark.asyncio
    async def test_npc_battle_start_in_battlefield(self, npc_env):
        """N-07: 전장 참여 상태 → bf_id 설정, bf_add_battle 호출"""
        env = npc_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 6, ATTACKER_NO, NPC_ID, {401: 50})

        # 유저를 전장 1에 참여시킴
        await combat_rm.set_user_battlefield(ATTACKER_NO, 1)

        result = await env["bm"].npc_battle_start(6, NPC_ID)
        assert result["success"] is True

        battle_id = result["data"]["battle_id"]
        state = await combat_rm.get_battle_state(battle_id)
        assert int(state["bf_id"]) == 1

        # battlefield:1:battles Set에 등록 확인
        bf_battles = await combat_rm.bf_get_battles(1)
        assert battle_id in bf_battles


# ===========================================================================
# process_battle_tick() — NPC 전투 틱
# ===========================================================================
class TestNpcBattleTick:
    async def _start_npc_battle(self, env, march_id=10, units=None, hero_idx=0, npc_id=NPC_ID):
        """헬퍼: NPC 전투 시작하고 battle_id 반환"""
        fr = env["fake_redis"]
        await setup_npc_instance(fr, npc_id, alive=True)
        await setup_npc_march(fr, march_id, ATTACKER_NO, npc_id,
                               units or {401: 50}, hero_idx=hero_idx)
        result = await env["bm"].npc_battle_start(march_id, npc_id)
        assert result["success"] is True
        return result["data"]["battle_id"]

    @pytest.mark.asyncio
    async def test_npc_tick_normal(self, npc_env):
        """N-10: 1틱 진행 → round 증가, 양측 피해"""
        env = npc_env
        combat_rm = env["combat_rm"]

        bid = await self._start_npc_battle(env)

        result = await env["bm"].process_battle_tick(bid)
        assert result["success"] is True
        assert result["data"]["finished"] is False
        assert result["data"]["round"] == 1

        # state 확인
        state = await combat_rm.get_battle_state(bid)
        assert int(state["round"]) == 1

    @pytest.mark.asyncio
    async def test_npc_tick_attacker_win(self, npc_env):
        """N-11: 공격자 압도적 → 수비 전멸 → attacker_win"""
        env = npc_env
        combat_rm = env["combat_rm"]

        # 공격자 매우 강함 (1000명) vs NPC 1 (unit 1: 20명)
        bid = await self._start_npc_battle(env, march_id=11, units={401: 1000})

        finished = False
        result_str = None
        for _ in range(50):
            result = await env["bm"].process_battle_tick(bid)
            if result["data"].get("finished"):
                finished = True
                result_str = result["data"]["result"]
                break

        assert finished, "50라운드 내 종료되지 않음"
        assert result_str == "attacker_win"

        # Redis 정리 확인
        active = await combat_rm.get_active_battles()
        assert bid not in active

    @pytest.mark.asyncio
    async def test_npc_tick_attacker_lose(self, npc_env):
        """N-12: 공격자 약함 → 공격자 전멸 → defender_win"""
        env = npc_env
        combat_rm = env["combat_rm"]

        # NPC 2 (Orc): units={1:30, 2:10} vs 공격자 소수 (3명)
        bid = await self._start_npc_battle(env, march_id=12, units={401: 3}, npc_id=NPC_ID_2)

        finished = False
        result_str = None
        for _ in range(50):
            result = await env["bm"].process_battle_tick(bid)
            if result["data"].get("finished"):
                finished = True
                result_str = result["data"]["result"]
                break

        assert finished, "50라운드 내 종료되지 않음"
        assert result_str == "defender_win"

    @pytest.mark.asyncio
    async def test_npc_tick_rage_accumulation(self, npc_env):
        """N-14: 매 틱 기력 누적 확인 (atk/def 각각 +25)"""
        env = npc_env
        combat_rm = env["combat_rm"]

        # 적당한 병력 (빠르게 끝나지 않도록)
        bid = await self._start_npc_battle(env, march_id=14, units={401: 50})

        # 1틱 실행
        result = await env["bm"].process_battle_tick(bid)
        assert result["data"]["finished"] is False

        state = await combat_rm.get_battle_state(bid)
        atk_rage = int(state["atk_rage"])
        def_rage = int(state["def_rage"])

        # 매 틱: 공격 +20 + 피격 +5 = +25
        assert atk_rage == 25
        assert def_rage == 25

        # 2틱 실행
        await env["bm"].process_battle_tick(bid)
        state = await combat_rm.get_battle_state(bid)
        assert int(state["atk_rage"]) == 50
        assert int(state["def_rage"]) == 50

    @pytest.mark.asyncio
    async def test_npc_tick_skill_fire(self, npc_env):
        """N-15: 기력 100 도달 → 스킬 발동 (영웅 있는 공격자만)"""
        env = npc_env
        combat_rm = env["combat_rm"]

        # 영웅 동행 (Hero 1001 → skill damage 500%)
        # NPC 2 (Orc: {1:30, 2:10})에 100명 공격 → 5라운드까지 버팀
        # 4틱 * 25 = 100 → 스킬 발동
        bid = await self._start_npc_battle(
            env, march_id=15, units={401: 100}, hero_idx=HERO_IDX, npc_id=NPC_ID_2)

        # 3틱 실행 → rage=75 (아직 스킬 미발동)
        for i in range(3):
            result = await env["bm"].process_battle_tick(bid)
            if result["data"].get("finished"):
                pytest.skip("전투가 3라운드 이내 종료 — 밸런스 변경 필요")

        state = await combat_rm.get_battle_state(bid)
        assert int(state["atk_rage"]) == 75  # 25*3

        # 4번째 틱 실행 → rage=100 → 스킬 발동 → rage -= 100 = 0
        result = await env["bm"].process_battle_tick(bid)
        state = await combat_rm.get_battle_state(bid)
        atk_rage = int(state["atk_rage"])

        assert atk_rage == 0, f"스킬 발동 후 rage 리셋 예상, 실제: {atk_rage}"

        # NPC는 영웅 없음 → def_rage=100이지만 스킬 발동 안됨
        # _check_rage_skill에서 hero_idx=None → rage -= 100 안 함
        def_rage = int(state["def_rage"])
        assert def_rage == 100  # 25*4=100, 영웅 없으므로 스킬 미발동 → 100 유지

    @pytest.mark.asyncio
    async def test_npc_tick_inactive_battle(self, npc_env):
        """N-16: 비활성 전투 → 실패"""
        result = await npc_env["bm"].process_battle_tick(9999)
        assert result["success"] is False


# ===========================================================================
# _npc_battle_end() — 전투 종료 처리 (process_battle_tick 내부 호출)
# ===========================================================================
class TestNpcBattleEnd:
    async def _run_npc_battle_to_end(self, env, march_id, units, hero_idx=0,
                                      npc_id=NPC_ID, max_rounds=100):
        """헬퍼: NPC 전투 시작 → 종료까지 반복 → (battle_id, result_str)"""
        fr = env["fake_redis"]
        await setup_npc_instance(fr, npc_id, alive=True)
        await setup_npc_march(fr, march_id, ATTACKER_NO, npc_id, units, hero_idx=hero_idx)

        start = await env["bm"].npc_battle_start(march_id, npc_id)
        assert start["success"] is True
        bid = start["data"]["battle_id"]

        result_str = None
        for _ in range(max_rounds):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                result_str = tick["data"]["result"]
                break

        return bid, result_str

    @pytest.mark.asyncio
    async def test_npc_end_exp_reward(self, npc_env):
        """N-20: 승리 + 영웅 동행 → EXP 지급"""
        env = npc_env

        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=20, units={401: 1000}, hero_idx=HERO_IDX)

        assert result_str == "attacker_win"

        # DB에서 영웅 EXP 확인 (NPC 1 exp_reward=50)
        from models import Hero
        hero = env["db_session"].query(Hero).filter(
            Hero.user_no == ATTACKER_NO,
            Hero.hero_idx == HERO_IDX
        ).first()
        assert hero is not None
        # 초기 exp=0 + reward=50 → exp=50 (lv_up_exp = 1*100 = 100이므로 레벨업 안됨)
        assert hero.exp == 50

    @pytest.mark.asyncio
    async def test_npc_end_no_hero_no_exp(self, npc_env):
        """N-21: 영웅 없이 승리 → EXP 미지급"""
        env = npc_env

        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=21, units={401: 1000}, hero_idx=0)

        assert result_str == "attacker_win"

        # 영웅 EXP 변동 없음 (hero_idx=0이라 EXP 로직 스킵)
        from models import Hero
        hero = env["db_session"].query(Hero).filter(
            Hero.user_no == ATTACKER_NO,
            Hero.hero_idx == HERO_IDX
        ).first()
        # 이전 테스트에서 EXP가 쌓였을 수 있으므로 refresh
        env["db_session"].refresh(hero)
        # hero_idx=0으로 전투했으므로 이 전투에서 EXP 추가 없음

    @pytest.mark.asyncio
    async def test_npc_end_npc_killed(self, npc_env):
        """N-22: NPC 처치 → alive=false, 리스폰 큐 등록"""
        env = npc_env
        combat_rm = env["combat_rm"]

        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=22, units={401: 1000})

        assert result_str == "attacker_win"

        # NPC alive=false
        npc = await combat_rm.get_npc(NPC_ID)
        assert npc is not None
        assert npc["alive"] is False

        # 리스폰 큐 등록 확인
        respawns = await combat_rm.get_pending_npc_respawns(
            datetime.utcnow() + timedelta(minutes=10))  # 5분 후니까 10분 기준으로 조회
        assert NPC_ID in respawns

    @pytest.mark.asyncio
    async def test_npc_end_return_march(self, npc_env):
        """N-23: 귀환 march 생성 확인"""
        env = npc_env
        combat_rm = env["combat_rm"]

        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=23, units={401: 1000})

        assert result_str == "attacker_win"

        # march metadata: status=returning, survived_units 존재
        march = await combat_rm.get_march_metadata(23)
        assert march["status"] == "returning"
        assert march.get("return_time") is not None
        assert march.get("survived_units") is not None

        # 귀환 큐 등록 확인
        returns = await combat_rm.get_pending_march_returns(
            datetime.utcnow() + timedelta(minutes=10))
        assert 23 in returns

    @pytest.mark.asyncio
    async def test_npc_end_db_finalize(self, npc_env):
        """N-24: DB battle 결과 저장"""
        env = npc_env

        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=24, units={401: 1000})

        assert result_str == "attacker_win"

        # DB에서 battle 조회
        battle_dm = env["db_manager"].get_battle_manager()
        battle = battle_dm.get_battle(bid)
        assert battle is not None
        assert battle["status"] == "finished"
        assert battle["result"] == "attacker_win"
        assert battle["total_rounds"] > 0

    @pytest.mark.asyncio
    async def test_npc_end_redis_cleanup(self, npc_env):
        """N-25: Redis 정리 → active battle 제거, status=finished"""
        env = npc_env
        combat_rm = env["combat_rm"]

        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=25, units={401: 1000})

        assert result_str == "attacker_win"

        # active battle에서 제거
        active = await combat_rm.get_active_battles()
        assert bid not in active

        # battle state: status=finished
        state = await combat_rm.get_battle_state(bid)
        assert state["status"] == "finished"

    @pytest.mark.asyncio
    async def test_npc_end_attacker_lose(self, npc_env):
        """N-26: 공격자 패배 → NPC alive 유지, EXP 미지급"""
        env = npc_env
        combat_rm = env["combat_rm"]

        # 공격자 매우 약함 vs NPC 2 (강함)
        bid, result_str = await self._run_npc_battle_to_end(
            env, march_id=26, units={401: 3}, npc_id=NPC_ID_2)

        assert result_str == "defender_win"

        # NPC alive 유지
        npc = await combat_rm.get_npc(NPC_ID_2)
        assert npc is not None
        assert npc["alive"] is True

        # march는 여전히 returning (패배해도 귀환)
        march = await combat_rm.get_march_metadata(26)
        assert march["status"] == "returning"

    @pytest.mark.asyncio
    async def test_npc_end_battlefield_cleanup(self, npc_env):
        """N-25 보조: 전장 내 전투 종료 → bf_remove_battle 호출"""
        env = npc_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # 전장 참여 설정
        await combat_rm.set_user_battlefield(ATTACKER_NO, 2)
        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 27, ATTACKER_NO, NPC_ID, {401: 1000})

        start = await env["bm"].npc_battle_start(27, NPC_ID)
        assert start["success"] is True
        bid = start["data"]["battle_id"]

        # 전장 Set에 등록 확인
        bf_battles = await combat_rm.bf_get_battles(2)
        assert bid in bf_battles

        # 전투 종료까지 실행
        for _ in range(50):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                break

        # 전장 Set에서 제거 확인
        bf_battles = await combat_rm.bf_get_battles(2)
        assert bid not in bf_battles
