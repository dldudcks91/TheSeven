"""
NPC 집결 전투 (Phase 3) 테스트
- rally_npc_battle_start(): Rally attack 도착 → NPC 집결 전투 시작
- _rally_npc_battle_end(): 전투 종료 → EXP(Leader만) + 유닛 분배 + 멤버별 귀환
- _distribute_survived_units(): 생존 유닛 비율 분배

테스트 인프라: conftest.py (theseven_test DB + fakeredis + AsyncClient)
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
    npc_data = {"npc_id": npc_id, "alive": alive, "x": x, "y": y, "respawn_at": None}
    await combat_rm.set_npc(npc_id, npc_data)


async def setup_rally(fake_redis, rally_id, leader_no, npc_id, hero_idx=0,
                       target_x=15, target_y=25, status="launched"):
    """Redis에 Rally 메타데이터 세팅"""
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)
    rally_data = {
        "rally_id": rally_id,
        "leader_no": leader_no,
        "target_type": "npc",
        "npc_id": npc_id,
        "hero_idx": hero_idx,
        "target_x": target_x,
        "target_y": target_y,
        "status": status,
    }
    await combat_rm.set_rally(rally_id, rally_data)


async def setup_rally_member(fake_redis, rally_id, user_no, units, march_id=None,
                               from_x=10, from_y=10):
    """Rally 멤버 등록"""
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)
    member_data = {
        "user_no": user_no,
        "units": {str(k): v for k, v in units.items()},
        "march_id": march_id,
        "from_x": from_x,
        "from_y": from_y,
        "status": "arrived",
    }
    await combat_rm.set_rally_member(rally_id, user_no, member_data)


async def setup_rally_march(fake_redis, march_id, leader_no, npc_id, units,
                              hero_idx=0, status="marching"):
    """Rally attack march metadata"""
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)
    metadata = {
        "march_id": march_id,
        "user_no": leader_no,
        "target_type": "rally_attack",
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


async def setup_map_position(fake_redis, user_no, x, y):
    await fake_redis.hset("map:positions", str(user_no), f"{x},{y}")


def create_battle_manager(db_session, fake_redis):
    from services.db_manager.DBManager import DBManager
    from services.redis_manager.RedisManager import RedisManager
    from services.game.BattleManager import BattleManager
    db_manager = DBManager(db_session)
    redis_manager = RedisManager(fake_redis)
    return BattleManager(db_manager, redis_manager), db_manager, redis_manager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEADER_NO = 99801
MEMBER_NO = 99802
NPC_ID = 1       # Goblin: units={1:20}, exp_reward=50, respawn=5min
NPC_ID_2 = 2     # Orc: units={1:30, 2:10}, exp_reward=120
HERO_IDX = 1001   # Arthur: atk=1.10
RALLY_ID = 100


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def setup_rally_users():
    """Rally용 유저 DB 생성 (Leader + Member)"""
    from tests.conftest import TestSessionLocal
    session = TestSessionLocal()
    try:
        from models import StatNation, Resources, Hero
        for user_no, name in [(LEADER_NO, "Leader"), (MEMBER_NO, "Member")]:
            session.add(StatNation(
                account_no=user_no, user_no=user_no, alliance_no=1,
                name=name, hq_lv=5, power=0,
                cr_dt=datetime.now(), last_dt=datetime.now(),
            ))
            session.add(Resources(
                user_no=user_no,
                food=100000, wood=100000, stone=100000, gold=100000, ruby=0,
            ))
        # Leader 영웅
        session.add(Hero(user_no=LEADER_NO, hero_idx=HERO_IDX, hero_lv=1, exp=0))
        session.commit()
    finally:
        session.close()


@pytest_asyncio.fixture
async def rally_env(fake_redis, setup_rally_users):
    """Rally NPC 전투 테스트 환경"""
    from tests.conftest import TestSessionLocal
    db_session = TestSessionLocal()

    bm, db_manager, redis_manager = create_battle_manager(db_session, fake_redis)
    combat_rm = redis_manager.get_combat_manager()

    await setup_map_position(fake_redis, LEADER_NO, 10, 10)
    await setup_map_position(fake_redis, MEMBER_NO, 20, 20)

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
# rally_npc_battle_start (R-01 ~ R-04)
# ===========================================================================
class TestRallyNpcBattleStart:

    @pytest.mark.asyncio
    async def test_rally_npc_start_normal(self, rally_env):
        """R-01: 정상 집결 전투 시작"""
        env = rally_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_rally(fr, RALLY_ID, LEADER_NO, NPC_ID, hero_idx=HERO_IDX)

        # 합산 유닛 march (Leader 60 + Member 40 = 100)
        combined_units = {401: 100}
        await setup_rally_march(fr, 1, LEADER_NO, NPC_ID, combined_units, hero_idx=HERO_IDX)

        # Rally 멤버 등록
        await setup_rally_member(fr, RALLY_ID, LEADER_NO, {401: 60}, march_id=None)
        await setup_rally_member(fr, RALLY_ID, MEMBER_NO, {401: 40}, march_id=2)

        result = await env["bm"].rally_npc_battle_start(1, NPC_ID, RALLY_ID)

        assert result["success"] is True
        assert result["data"]["battle_type"] == "rally_npc"
        assert result["data"]["rally_id"] == RALLY_ID

        # Redis 전투 상태
        bid = result["data"]["battle_id"]
        state = await combat_rm.get_battle_state(bid)
        assert state is not None
        assert state["battle_type"] == "rally_npc"
        assert int(state["rally_id"]) == RALLY_ID
        assert int(state["hero_idx"]) == HERO_IDX

        # active battle 등록
        active = await combat_rm.get_active_battles()
        assert bid in active

    @pytest.mark.asyncio
    async def test_rally_npc_start_dead_npc(self, rally_env):
        """R-02: NPC dead -> 실패 + march 귀환"""
        env = rally_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=False)
        await setup_rally(fr, RALLY_ID + 1, LEADER_NO, NPC_ID)
        await setup_rally_march(fr, 3, LEADER_NO, NPC_ID, {401: 50})

        result = await env["bm"].rally_npc_battle_start(3, NPC_ID, RALLY_ID + 1)
        assert result["success"] is False

        march = await combat_rm.get_march_metadata(3)
        assert march["status"] == "returning"

    @pytest.mark.asyncio
    async def test_rally_npc_start_no_rally(self, rally_env):
        """R-03: rally 정보 없음 -> 실패"""
        env = rally_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_rally_march(fr, 4, LEADER_NO, NPC_ID, {401: 50})

        # rally_id=999 (존재하지 않음)
        result = await env["bm"].rally_npc_battle_start(4, NPC_ID, 999)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_rally_npc_start_already_processed(self, rally_env):
        """R-04: march status != marching -> 실패"""
        env = rally_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_rally(fr, RALLY_ID + 3, LEADER_NO, NPC_ID)
        await setup_rally_march(fr, 5, LEADER_NO, NPC_ID, {401: 50}, status="battling")

        result = await env["bm"].rally_npc_battle_start(5, NPC_ID, RALLY_ID + 3)
        assert result["success"] is False


# ===========================================================================
# _rally_npc_battle_end (R-10 ~ R-14) — process_battle_tick 내부 호출
# ===========================================================================
class TestRallyNpcBattleEnd:

    async def _start_and_run(self, env, march_id, rally_id, units, hero_idx=0,
                              npc_id=NPC_ID, max_rounds=100):
        """헬퍼: Rally NPC 전투 시작 → 종료까지"""
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, npc_id, alive=True)
        await setup_rally(fr, rally_id, LEADER_NO, npc_id, hero_idx=hero_idx)
        await setup_rally_march(fr, march_id, LEADER_NO, npc_id, units, hero_idx=hero_idx)

        start = await env["bm"].rally_npc_battle_start(march_id, npc_id, rally_id)
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
    async def test_rally_npc_end_exp_leader_only(self, rally_env):
        """R-10: 승리 → Leader 영웅에게만 EXP"""
        env = rally_env
        fr = env["fake_redis"]

        # 멤버 등록 (전투 종료 시 유닛 분배에 사용)
        await setup_rally_member(fr, 200, LEADER_NO, {401: 600}, march_id=None, from_x=10, from_y=10)
        await setup_rally_member(fr, 200, MEMBER_NO, {401: 400}, march_id=12, from_x=20, from_y=20)

        bid, result_str = await self._start_and_run(
            env, march_id=10, rally_id=200, units={401: 1000}, hero_idx=HERO_IDX)

        assert result_str == "attacker_win"

        # Leader 영웅 EXP 확인 (NPC 1: exp_reward=50)
        from models import Hero
        hero = env["db_session"].query(Hero).filter(
            Hero.user_no == LEADER_NO, Hero.hero_idx == HERO_IDX
        ).first()
        assert hero is not None
        assert hero.exp == 50

    @pytest.mark.asyncio
    async def test_rally_npc_end_npc_killed(self, rally_env):
        """R-11: NPC alive=false, 리스폰 큐 등록"""
        env = rally_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_rally_member(fr, 201, LEADER_NO, {401: 1000}, march_id=None)

        bid, result_str = await self._start_and_run(
            env, march_id=11, rally_id=201, units={401: 1000})

        assert result_str == "attacker_win"

        npc = await combat_rm.get_npc(NPC_ID)
        assert npc["alive"] is False

    @pytest.mark.asyncio
    async def test_rally_npc_end_member_return_marches(self, rally_env):
        """R-12: 멤버별 개별 귀환 march 생성"""
        env = rally_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        # Member에게 march_id 부여 + Member march metadata 생성
        await setup_rally_member(fr, 202, LEADER_NO, {401: 600}, march_id=None, from_x=10, from_y=10)
        await setup_rally_member(fr, 202, MEMBER_NO, {401: 400}, march_id=14, from_x=20, from_y=20)

        # Member의 gather march metadata (rally_npc_battle_end에서 update 대상)
        await setup_rally_march(fr, 14, MEMBER_NO, NPC_ID, {401: 400}, status="arrived")

        bid, result_str = await self._start_and_run(
            env, march_id=13, rally_id=202, units={401: 1000})

        assert result_str == "attacker_win"

        # Member(march_id=14)의 march가 returning으로 업데이트
        member_march = await combat_rm.get_march_metadata(14)
        assert member_march is not None
        assert member_march["status"] == "returning"
        assert member_march.get("survived_units") is not None

    @pytest.mark.asyncio
    async def test_rally_npc_end_attack_march_deleted(self, rally_env):
        """R-13: attack march 정리"""
        env = rally_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_rally_member(fr, 203, LEADER_NO, {401: 1000}, march_id=None)

        bid, result_str = await self._start_and_run(
            env, march_id=15, rally_id=203, units={401: 1000})

        assert result_str == "attacker_win"

        # attack march(15) 삭제 확인
        march = await combat_rm.get_march_metadata(15)
        assert march is None

    @pytest.mark.asyncio
    async def test_rally_npc_end_rally_status_done(self, rally_env):
        """R-14: rally status=done"""
        env = rally_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_rally_member(fr, 204, LEADER_NO, {401: 1000}, march_id=None)

        bid, result_str = await self._start_and_run(
            env, march_id=16, rally_id=204, units={401: 1000})

        assert result_str == "attacker_win"

        rally = await combat_rm.get_rally(204)
        assert rally["status"] == "done"


# ===========================================================================
# _distribute_survived_units (D-01 ~ D-06)
# ===========================================================================
class TestDistributeSurvivedUnits:
    """순수 정적 메서드 테스트 — DB/Redis 불필요"""

    def _distribute(self, members, atk_alive, leader_no=0):
        from services.game.BattleManager import BattleManager
        return BattleManager._distribute_survived_units(members, atk_alive, leader_no)

    def test_distribute_proportional(self, load_game_data):
        """D-01: 2명(A:60, B:40) → 생존 50 → A:30, B:20"""
        members = {
            1: {"units": {"401": 60}},
            2: {"units": {"401": 40}},
        }
        atk_alive = {401: 50}

        result = self._distribute(members, atk_alive, leader_no=1)

        assert result[1][401] == 30  # 50 * 60/100 = 30
        assert result[2][401] == 20  # 50 * 40/100 = 20

    def test_distribute_remainder_to_leader(self, load_game_data):
        """D-02: 나머지 유닛 → Leader에게"""
        members = {
            1: {"units": {"401": 33}},
            2: {"units": {"401": 33}},
            3: {"units": {"401": 34}},
        }
        atk_alive = {401: 50}

        result = self._distribute(members, atk_alive, leader_no=1)

        # floor: 1→50*33/100=16, 2→16, 3→17 = 49, 나머지 1 → leader(1)
        total = sum(result[m].get(401, 0) for m in [1, 2, 3])
        assert total == 50
        assert result[1][401] >= result[2][401]  # leader가 나머지 받음

    def test_distribute_one_type_eliminated(self, load_game_data):
        """D-03: 특정 유닛 전멸(생존 0) → 해당 유닛 분배 없음"""
        members = {
            1: {"units": {"401": 50, "402": 30}},
            2: {"units": {"401": 50, "402": 20}},
        }
        atk_alive = {401: 40}  # 402 전멸

        result = self._distribute(members, atk_alive, leader_no=1)

        assert result[1].get(402, 0) == 0
        assert result[2].get(402, 0) == 0
        assert result[1].get(401, 0) + result[2].get(401, 0) == 40

    def test_distribute_empty_members(self, load_game_data):
        """D-04: 멤버 없음 → 빈 결과"""
        result = self._distribute({}, {401: 50}, leader_no=1)
        assert result == {}

    def test_distribute_empty_alive(self, load_game_data):
        """D-04b: 생존 유닛 없음 → 빈 결과"""
        members = {1: {"units": {"401": 50}}}
        result = self._distribute(members, {}, leader_no=1)
        assert result == {}

    def test_distribute_mixed_unit_types(self, load_game_data):
        """D-05: 보병+기병 혼합 → 유닛 타입별 독립 분배"""
        members = {
            1: {"units": {"401": 60, "402": 40}},
            2: {"units": {"401": 40, "402": 60}},
        }
        atk_alive = {401: 50, 402: 80}

        result = self._distribute(members, atk_alive, leader_no=1)

        # 401: 1→50*60/100=30, 2→50*40/100=20
        assert result[1].get(401, 0) + result[2].get(401, 0) == 50
        # 402: 1→80*40/100=32, 2→80*60/100=48
        assert result[1].get(402, 0) + result[2].get(402, 0) == 80

    def test_distribute_single_member(self, load_game_data):
        """D-06: 1명만 참여 → 전체 생존 유닛 수령"""
        members = {1: {"units": {"401": 100}}}
        atk_alive = {401: 80}

        result = self._distribute(members, atk_alive, leader_no=1)

        assert result[1][401] == 80
