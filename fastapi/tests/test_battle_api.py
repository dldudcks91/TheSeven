"""
전투 API + 엣지케이스 (Phase 4 + Phase 5) 테스트
- battle_info (9021): 진행 중 전투 조회 (Redis → DB 폴백)
- battle_report (9022): 전투 보고서 목록 (DB)
- 엣지케이스: 병력 1:1, 동시 march, NPC 리스폰 중 공격 등

테스트 인프라: conftest.py (AsyncClient + theseven_test DB + fakeredis)
"""

import pytest
import pytest_asyncio
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

async def setup_npc_instance(fake_redis, npc_id, alive=True):
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)
    await combat_rm.set_npc(npc_id, {"npc_id": npc_id, "alive": alive, "x": 15, "y": 25})


async def setup_npc_march(fake_redis, march_id, attacker_no, npc_id,
                           units, hero_idx=0, status="marching"):
    from services.redis_manager.combat_redis_manager import CombatRedisManager
    combat_rm = CombatRedisManager(fake_redis)
    metadata = {
        "march_id": march_id, "user_no": attacker_no,
        "target_type": "npc", "target_user_no": 0, "npc_id": npc_id,
        "units": {str(k): v for k, v in units.items()},
        "hero_idx": hero_idx,
        "from_x": 10, "from_y": 10, "to_x": 15, "to_y": 25,
        "march_speed": 10, "status": status,
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

ATTACKER_NO = 99701
ATTACKER2_NO = 99702
NPC_ID = 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def setup_api_users():
    """API 테스트용 유저 DB 생성"""
    from tests.conftest import TestSessionLocal
    session = TestSessionLocal()
    try:
        from models import StatNation, Resources
        for user_no, name in [(ATTACKER_NO, "ApiUser1"), (ATTACKER2_NO, "ApiUser2")]:
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


# ===========================================================================
# battle_info (9021) — A-01 ~ A-05
# ===========================================================================
class TestBattleInfo:

    @pytest.mark.asyncio
    async def test_battle_info_active(self, client, fake_redis, setup_api_users):
        """A-01: 진행 중 전투 → Redis 데이터 반환"""
        await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)
        await setup_npc_instance(fake_redis, NPC_ID, alive=True)
        await setup_npc_march(fake_redis, 1, ATTACKER_NO, NPC_ID, {401: 50})

        from tests.conftest import TestSessionLocal
        db_session = TestSessionLocal()
        bm, _, _ = create_battle_manager(db_session, fake_redis)
        result = await bm.npc_battle_start(1, NPC_ID)
        db_session.close()
        assert result["success"] is True
        battle_id = result["data"]["battle_id"]

        # API 호출
        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9021,
            "data": {"battle_id": battle_id},
        })
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["battle_type"] == "npc"

    @pytest.mark.asyncio
    async def test_battle_info_finished_from_db(self, client, fake_redis, setup_api_users):
        """A-02: 종료 전투 → DB 폴백"""
        await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)
        await setup_npc_instance(fake_redis, NPC_ID, alive=True)
        await setup_npc_march(fake_redis, 2, ATTACKER_NO, NPC_ID, {401: 1000})

        from tests.conftest import TestSessionLocal
        db_session = TestSessionLocal()
        bm, _, _ = create_battle_manager(db_session, fake_redis)
        result = await bm.npc_battle_start(2, NPC_ID)
        bid = result["data"]["battle_id"]

        # 전투 종료까지 실행
        for _ in range(50):
            tick = await bm.process_battle_tick(bid)
            if tick["data"].get("finished"):
                break
        db_session.close()

        # API 호출 — DB 폴백
        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9021,
            "data": {"battle_id": bid},
        })
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "finished"

    @pytest.mark.asyncio
    async def test_battle_info_not_found(self, client, fake_redis, setup_api_users):
        """A-03: 존재하지 않는 battle_id → 실패"""
        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9021,
            "data": {"battle_id": 99999},
        })
        body = resp.json()
        assert body["success"] is False

    @pytest.mark.asyncio
    async def test_battle_info_no_permission(self, client, fake_redis, setup_api_users):
        """A-04: 다른 유저의 전투 → 권한 없음"""
        await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)
        await setup_npc_instance(fake_redis, NPC_ID, alive=True)
        await setup_npc_march(fake_redis, 3, ATTACKER_NO, NPC_ID, {401: 50})

        from tests.conftest import TestSessionLocal
        db_session = TestSessionLocal()
        bm, _, _ = create_battle_manager(db_session, fake_redis)
        result = await bm.npc_battle_start(3, NPC_ID)
        bid = result["data"]["battle_id"]
        db_session.close()

        # 다른 유저로 조회
        resp = await client.post("/api", json={
            "user_no": ATTACKER2_NO,
            "api_code": 9021,
            "data": {"battle_id": bid},
        })
        body = resp.json()
        assert body["success"] is False

    @pytest.mark.asyncio
    async def test_battle_info_missing_battle_id(self, client, fake_redis, setup_api_users):
        """A-05: battle_id 누락 → 실패"""
        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9021,
            "data": {},
        })
        body = resp.json()
        assert body["success"] is False


# ===========================================================================
# battle_report (9022) — A-10 ~ A-12
# ===========================================================================
class TestBattleReport:

    @pytest.mark.asyncio
    async def test_battle_report_empty(self, client, fake_redis, setup_api_users):
        """A-10: 전투 이력 없음 → 빈 리스트"""
        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9022,
            "data": {},
        })
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["reports"] == []

    @pytest.mark.asyncio
    async def test_battle_report_with_data(self, client, fake_redis, setup_api_users):
        """A-11: 전투 종료 후 → 보고서 포함"""
        await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)
        await setup_npc_instance(fake_redis, NPC_ID, alive=True)
        await setup_npc_march(fake_redis, 10, ATTACKER_NO, NPC_ID, {401: 1000})

        from tests.conftest import TestSessionLocal
        db_session = TestSessionLocal()
        bm, _, _ = create_battle_manager(db_session, fake_redis)
        result = await bm.npc_battle_start(10, NPC_ID)
        bid = result["data"]["battle_id"]
        for _ in range(50):
            tick = await bm.process_battle_tick(bid)
            if tick["data"].get("finished"):
                break
        db_session.close()

        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9022,
            "data": {},
        })
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["reports"]) >= 1

    @pytest.mark.asyncio
    async def test_battle_report_limit(self, client, fake_redis, setup_api_users):
        """A-12: limit=1 → 최대 1건"""
        await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)

        from tests.conftest import TestSessionLocal
        db_session = TestSessionLocal()
        bm, _, _ = create_battle_manager(db_session, fake_redis)

        # 2건의 전투 종료
        for i in range(2):
            await setup_npc_instance(fake_redis, NPC_ID, alive=True)
            await setup_npc_march(fake_redis, 20 + i, ATTACKER_NO, NPC_ID, {401: 1000})
            result = await bm.npc_battle_start(20 + i, NPC_ID)
            bid = result["data"]["battle_id"]
            for _ in range(50):
                tick = await bm.process_battle_tick(bid)
                if tick["data"].get("finished"):
                    break
        db_session.close()

        resp = await client.post("/api", json={
            "user_no": ATTACKER_NO,
            "api_code": 9022,
            "data": {"limit": 1},
        })
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["reports"]) == 1


# ===========================================================================
# Phase 5: 엣지케이스 & 동시성 (EC, CC, IC)
# ===========================================================================

@pytest_asyncio.fixture
async def edge_env(fake_redis, setup_api_users):
    """엣지케이스 테스트 환경"""
    from tests.conftest import TestSessionLocal
    db_session = TestSessionLocal()
    bm, db_manager, redis_manager = create_battle_manager(db_session, fake_redis)
    combat_rm = redis_manager.get_combat_manager()
    await setup_map_position(fake_redis, ATTACKER_NO, 10, 10)

    yield {
        "bm": bm, "db_manager": db_manager, "redis_manager": redis_manager,
        "combat_rm": combat_rm, "fake_redis": fake_redis, "db_session": db_session,
    }
    db_session.close()


class TestEdgeCases:
    """EC: 데이터 경계 테스트"""

    @pytest.mark.asyncio
    async def test_1v1_battle_draw(self, edge_env):
        """EC-01: 공격자 1명 vs 수비 1명 (NPC 유닛 1개로 시뮬레이션)"""
        # NPC 유닛이 최소인 경우에도 전투 시작/종료가 정상 동작하는지
        env = edge_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 50, ATTACKER_NO, NPC_ID, {401: 1})

        result = await env["bm"].npc_battle_start(50, NPC_ID)
        assert result["success"] is True
        bid = result["data"]["battle_id"]

        finished = False
        for _ in range(50):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                finished = True
                break

        assert finished, "1:1 전투가 종료되어야 함"

    @pytest.mark.asyncio
    async def test_invalid_npc_units(self, edge_env):
        """EC-04: NPC CSV에 없는 npc_id → 전투 시작 실패"""
        env = edge_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, 9999, alive=True)
        await setup_npc_march(fr, 51, ATTACKER_NO, 9999, {401: 50})

        result = await env["bm"].npc_battle_start(51, 9999)
        assert result["success"] is False


class TestConcurrency:
    """CC: 동시성 시나리오"""

    @pytest.mark.asyncio
    async def test_double_battle_start(self, edge_env):
        """CC-01: 같은 march_id로 battle_start 2회 → 두 번째 실패"""
        env = edge_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 60, ATTACKER_NO, NPC_ID, {401: 50})

        result1 = await env["bm"].npc_battle_start(60, NPC_ID)
        assert result1["success"] is True

        # 두 번째 호출: status가 "battling"으로 변경되었으므로 실패
        result2 = await env["bm"].npc_battle_start(60, NPC_ID)
        assert result2["success"] is False

    @pytest.mark.asyncio
    async def test_tick_after_battle_end(self, edge_env):
        """CC-02: 전투 종료 직후 tick → 비활성 전투"""
        env = edge_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 61, ATTACKER_NO, NPC_ID, {401: 1000})

        result = await env["bm"].npc_battle_start(61, NPC_ID)
        bid = result["data"]["battle_id"]

        # 종료까지 실행
        for _ in range(50):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                break

        # 종료 후 추가 tick → 실패
        extra = await env["bm"].process_battle_tick(bid)
        assert extra["success"] is False

    @pytest.mark.asyncio
    async def test_npc_dead_concurrent_attack(self, edge_env):
        """CC-04: NPC 리스폰 중 공격 → alive=false → 전투 거부"""
        env = edge_env
        fr = env["fake_redis"]

        await setup_npc_instance(fr, NPC_ID, alive=False)
        await setup_npc_march(fr, 62, ATTACKER_NO, NPC_ID, {401: 50})

        result = await env["bm"].npc_battle_start(62, NPC_ID)
        assert result["success"] is False


class TestIntegrity:
    """IC: 정합성 테스트"""

    @pytest.mark.asyncio
    async def test_npc_alive_after_attacker_lose(self, edge_env):
        """IC-01: 공격자 패배 → NPC alive=true"""
        env = edge_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, 2, alive=True)  # NPC 2 (강함)
        await setup_npc_march(fr, 70, ATTACKER_NO, 2, {401: 3})

        result = await env["bm"].npc_battle_start(70, 2)
        bid = result["data"]["battle_id"]

        for _ in range(100):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                break

        npc = await combat_rm.get_npc(2)
        assert npc["alive"] is True

    @pytest.mark.asyncio
    async def test_npc_dead_after_attacker_win(self, edge_env):
        """IC-01b: 공격자 승리 → NPC alive=false"""
        env = edge_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 71, ATTACKER_NO, NPC_ID, {401: 1000})

        result = await env["bm"].npc_battle_start(71, NPC_ID)
        bid = result["data"]["battle_id"]

        for _ in range(50):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                break

        npc = await combat_rm.get_npc(NPC_ID)
        assert npc["alive"] is False

    @pytest.mark.asyncio
    async def test_active_battle_cleanup(self, edge_env):
        """IC-02: 전투 종료 → active_battle Set에서 제거"""
        env = edge_env
        fr = env["fake_redis"]
        combat_rm = env["combat_rm"]

        await setup_npc_instance(fr, NPC_ID, alive=True)
        await setup_npc_march(fr, 72, ATTACKER_NO, NPC_ID, {401: 1000})

        result = await env["bm"].npc_battle_start(72, NPC_ID)
        bid = result["data"]["battle_id"]

        # active에 있는지 확인
        active = await combat_rm.get_active_battles()
        assert bid in active

        for _ in range(50):
            tick = await env["bm"].process_battle_tick(bid)
            if tick["data"].get("finished"):
                break

        active = await combat_rm.get_active_battles()
        assert bid not in active

    @pytest.mark.asyncio
    async def test_rally_unit_distribution_sum(self, edge_env):
        """IC-06: Rally 유닛 분배 합산 = 생존 유닛"""
        from services.game.BattleManager import BattleManager

        members = {
            1: {"units": {"401": 60, "402": 30}},
            2: {"units": {"401": 40, "402": 20}},
            3: {"units": {"401": 30, "402": 50}},
        }
        atk_alive = {401: 80, 402: 60}

        result = BattleManager._distribute_survived_units(members, atk_alive, leader_no=1)

        # 유닛 타입별 합산 = 생존 유닛
        for uid in [401, 402]:
            total = sum(result[m].get(uid, 0) for m in [1, 2, 3])
            assert total == atk_alive[uid], f"unit {uid}: 분배 합={total}, 생존={atk_alive[uid]}"
