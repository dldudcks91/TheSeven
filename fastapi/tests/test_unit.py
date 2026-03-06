"""
Unit API (4xxx) 테스트
- 4001: unit_info (유닛 정보 조회)
- 4002: unit_train (유닛 훈련)
- 4003: unit_upgrade (유닛 업그레이드)

테스트 인프라: conftest.py (theseven_test DB + fakeredis + AsyncClient)

유닛 설정 (unit_info.csv):
- 401: Infantry Tier1, time=2s, food=100
- 402: Infantry Tier2, time=4s, food=200
- 411: Cavalry Tier1, time=2s, food=100

UNIT_TYPE_MAP: {401:0, 402:0, 403:0, 404:0, 411:1, ...}
→ 같은 unit_type에서 동시 훈련 불가
"""

import pytest
import pytest_asyncio
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

async def call_api(client, user_no, api_code, data=None):
    resp = await client.post("/api", json={
        "user_no": user_no,
        "api_code": api_code,
        "data": data or {}
    })
    return resp


async def setup_resources(fake_redis, user_no, food=100000, wood=100000, stone=100000, gold=100000, ruby=1000):
    """Redis에 자원 세팅"""
    hash_key = f"user_data:{user_no}:resources"
    await fake_redis.hset(hash_key, mapping={
        "food": str(food),
        "wood": str(wood),
        "stone": str(stone),
        "gold": str(gold),
        "ruby": str(ruby),
    })


async def setup_unit_in_cache(fake_redis, user_no, unit_idx, **overrides):
    """Redis 캐시에 유닛 데이터 직접 세팅"""
    unit_data = {
        "user_no": user_no,
        "unit_idx": unit_idx,
        "total": 0,
        "ready": 0,
        "training": 0,
        "upgrading": 0,
        "field": 0,
        "injured": 0,
        "wounded": 0,
        "healing": 0,
        "death": 0,
        "training_end_time": None,
        "cached_at": datetime.utcnow().isoformat(),
    }
    unit_data.update(overrides)

    hash_key = f"user_data:{user_no}:unit"
    await fake_redis.hset(hash_key, str(unit_idx), json.dumps(unit_data))
    return unit_data


async def setup_training_task(fake_redis, user_no, unit_type, unit_idx, quantity=10,
                               seconds_remaining=60, task_type=0, target_unit_idx=None):
    """Redis에 진행 중인 훈련/업그레이드 태스크 세팅"""
    completion_time = datetime.utcnow() + timedelta(seconds=seconds_remaining)
    queue_key = "completion_queue:unit_training"
    member = f"{user_no}:{unit_type}:{unit_idx}"

    # Sorted Set에 추가
    await fake_redis.zadd(queue_key, {member: completion_time.timestamp()})

    # Metadata 저장
    metadata_key = f"{queue_key}:metadata:{member}"
    metadata = {
        "user_no": str(user_no),
        "unit_type": str(unit_type),
        "unit_idx": str(unit_idx),
        "task_type": str(task_type),
        "quantity": str(quantity),
        "added_at": str(datetime.utcnow().timestamp()),
    }
    if target_unit_idx is not None:
        metadata["target_unit_idx"] = str(target_unit_idx)
    await fake_redis.hmset(metadata_key, mapping=metadata)

    return completion_time


# ===========================================================================
# 4001 - 유닛 정보 조회
# ===========================================================================
class TestUnitInfo:
    @pytest.mark.asyncio
    async def test_info_empty(self, client, fake_redis, create_test_user, test_user_no):
        """유닛 없는 상태 → 빈 데이터"""
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        assert result["success"] is True
        assert result["data"] == {} or len(result["data"]) == 0

    @pytest.mark.asyncio
    async def test_info_with_unit(self, client, fake_redis, create_test_user, test_user_no):
        """Redis에 유닛 존재 시 정상 조회"""
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=50, ready=50)
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        assert result["success"] is True
        assert "401" in result["data"]
        assert result["data"]["401"]["total"] == 50


# ===========================================================================
# 4002 - 유닛 훈련
# ===========================================================================
class TestUnitTrain:
    @pytest.mark.asyncio
    async def test_train_success(self, client, fake_redis, create_test_user, test_user_no):
        """정상 훈련: 유닛 생성 + training 증가"""
        await setup_resources(fake_redis, test_user_no)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        result = resp.json()
        assert result["success"] is True
        assert "training" in result["message"].lower() or "train" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_train_missing_unit_idx(self, client, fake_redis, create_test_user, test_user_no):
        """unit_idx 누락 → 실패"""
        resp = await call_api(client, test_user_no, 4002, {"quantity": 5})
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_train_invalid_unit_idx(self, client, fake_redis, create_test_user, test_user_no):
        """존재하지 않는 unit_idx → 실패"""
        await setup_resources(fake_redis, test_user_no)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 999, "quantity": 5})
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_train_zero_quantity(self, client, fake_redis, create_test_user, test_user_no):
        """quantity 0 → 실패"""
        await setup_resources(fake_redis, test_user_no)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 0})
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_train_insufficient_resources(self, client, fake_redis, create_test_user, test_user_no):
        """자원 부족 → 실패"""
        await setup_resources(fake_redis, test_user_no, food=10)  # 401 Tier1: food=100 * 5 = 500 필요
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_train_duplicate_same_type(self, client, fake_redis, create_test_user, test_user_no):
        """동일 unit_type 중복 훈련 → 거부"""
        await setup_resources(fake_redis, test_user_no)
        # 먼저 401(infantry, type=0) 훈련 중 태스크 세팅
        await setup_training_task(fake_redis, test_user_no, unit_type=0, unit_idx=401, quantity=5)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, training=5)

        # 같은 타입(infantry) 402 훈련 시도
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 402, "quantity": 3})
        result = resp.json()
        assert result["success"] is False
        assert "already" in result["message"].lower() or "progress" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_train_consumes_resources(self, client, fake_redis, create_test_user, test_user_no):
        """자원 소모 확인: 401 * 5 = food 500"""
        await setup_resources(fake_redis, test_user_no, food=1000)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        result = resp.json()
        assert result["success"] is True

        # 자원 확인
        hash_key = f"user_data:{test_user_no}:resources"
        remaining_food = await fake_redis.hget(hash_key, "food")
        assert int(remaining_food) == 500  # 1000 - (100 * 5)

    @pytest.mark.asyncio
    async def test_train_different_type_allowed(self, client, fake_redis, create_test_user, test_user_no):
        """다른 unit_type은 동시 훈련 가능 (infantry 훈련 중 → cavalry 가능)"""
        await setup_resources(fake_redis, test_user_no)
        # infantry(type=0) 훈련 중
        await setup_training_task(fake_redis, test_user_no, unit_type=0, unit_idx=401, quantity=5)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, training=5)

        # cavalry(type=1) 훈련 시도 → 성공해야 함
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 411, "quantity": 3})
        result = resp.json()
        assert result["success"] is True


# ===========================================================================
# 4003 - 유닛 업그레이드
# ===========================================================================
class TestUnitUpgrade:
    @pytest.mark.asyncio
    async def test_upgrade_success(self, client, fake_redis, create_test_user, test_user_no):
        """정상 업그레이드: ready 감소, upgrading 증가"""
        await setup_resources(fake_redis, test_user_no)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "target_unit_idx": 402, "quantity": 5
        })
        result = resp.json()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_upgrade_not_enough_ready(self, client, fake_redis, create_test_user, test_user_no):
        """ready 부족 → 실패"""
        await setup_resources(fake_redis, test_user_no)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=3, ready=3)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "target_unit_idx": 402, "quantity": 5
        })
        result = resp.json()
        assert result["success"] is False
        assert "not enough" in result["message"].lower() or "available" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_upgrade_missing_target(self, client, fake_redis, create_test_user, test_user_no):
        """target_unit_idx 누락 → 실패"""
        await setup_resources(fake_redis, test_user_no)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "quantity": 5
        })
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_upgrade_duplicate_same_type(self, client, fake_redis, create_test_user, test_user_no):
        """동일 unit_type 작업 중 업그레이드 → 거부"""
        await setup_resources(fake_redis, test_user_no)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)
        # infantry(type=0) 훈련 중
        await setup_training_task(fake_redis, test_user_no, unit_type=0, unit_idx=401, quantity=5)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "target_unit_idx": 402, "quantity": 3
        })
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_upgrade_consumes_resources(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 자원 소모 확인: target(402) 기준 food=200 * 3 = 600"""
        await setup_resources(fake_redis, test_user_no, food=1000)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "target_unit_idx": 402, "quantity": 3
        })
        result = resp.json()
        assert result["success"] is True

        hash_key = f"user_data:{test_user_no}:resources"
        remaining_food = await fake_redis.hget(hash_key, "food")
        assert int(remaining_food) == 400  # 1000 - (200 * 3)


# ===========================================================================
# 통합 플로우
# ===========================================================================
class TestUnitFlow:
    @pytest.mark.asyncio
    async def test_train_then_info(self, client, fake_redis, create_test_user, test_user_no):
        """훈련 시작 → info 조회 시 training 반영 확인"""
        await setup_resources(fake_redis, test_user_no)
        # 훈련 시작
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        assert resp.json()["success"] is True

        # info 조회
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        assert result["success"] is True
        assert "401" in result["data"]
        assert result["data"]["401"]["training"] == 5

    @pytest.mark.asyncio
    async def test_upgrade_updates_ready_and_upgrading(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 시 ready 감소, upgrading 증가 확인"""
        await setup_resources(fake_redis, test_user_no)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "target_unit_idx": 402, "quantity": 3
        })
        assert resp.json()["success"] is True

        # info 조회
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        unit_401 = result["data"]["401"]
        assert unit_401["ready"] == 7   # 10 - 3
        assert unit_401["upgrading"] == 3


# ===========================================================================
# 4004 - 유닛 완료 (unit_finish)
# ===========================================================================
class TestUnitFinish:
    @pytest.mark.asyncio
    async def test_finish_success(self, client, fake_redis, create_test_user, test_user_no):
        """훈련 완료: 시간 경과 후 finish → training 감소, ready 증가"""
        await setup_resources(fake_redis, test_user_no)
        # 훈련 시작
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        assert resp.json()["success"] is True

        # 완료 시간을 과거로 변경 (즉시 완료 가능하도록)
        unit_type = 0  # infantry
        queue_key = "completion_queue:unit_training"
        member = f"{test_user_no}:{unit_type}:401"
        past_time = datetime.utcnow() - timedelta(seconds=10)
        await fake_redis.zadd(queue_key, {member: past_time.timestamp()})

        # 완료 요청
        resp = await call_api(client, test_user_no, 4004, {"unit_idx": 401, "unit_type": 0})
        result = resp.json()
        assert result["success"] is True

        # info 조회 → training=0, ready=5
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        unit_401 = result["data"]["401"]
        assert unit_401["training"] == 0
        assert unit_401["ready"] == 5

    @pytest.mark.asyncio
    async def test_finish_not_ready(self, client, fake_redis, create_test_user, test_user_no):
        """시간 미경과 → 실패 + remaining 메시지"""
        await setup_resources(fake_redis, test_user_no)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        assert resp.json()["success"] is True

        # 완료 시도 (아직 시간 안 지남)
        resp = await call_api(client, test_user_no, 4004, {"unit_idx": 401, "unit_type": 0})
        result = resp.json()
        assert result["success"] is False
        assert "remaining" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_finish_no_task(self, client, fake_redis, create_test_user, test_user_no):
        """진행 중인 작업 없이 finish → 실패"""
        resp = await call_api(client, test_user_no, 4004, {"unit_idx": 401, "unit_type": 0})
        result = resp.json()
        assert result["success"] is False


# ===========================================================================
# 4005 - 유닛 취소 (unit_cancel)
# ===========================================================================
class TestUnitCancel:
    @pytest.mark.asyncio
    async def test_cancel_train_success(self, client, fake_redis, create_test_user, test_user_no):
        """훈련 취소: training 감소 + 자원 환불"""
        await setup_resources(fake_redis, test_user_no, food=1000)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        assert resp.json()["success"] is True

        # 자원 확인: 1000 - 500 = 500
        hash_key = f"user_data:{test_user_no}:resources"
        remaining = await fake_redis.hget(hash_key, "food")
        assert int(remaining) == 500

        # 취소
        resp = await call_api(client, test_user_no, 4005, {"unit_idx": 401})
        result = resp.json()
        assert result["success"] is True
        assert "cancel" in result["message"].lower()

        # 자원 환불 확인: 500 + 500 = 1000
        remaining = await fake_redis.hget(hash_key, "food")
        assert int(remaining) == 1000

        # info 조회 → training=0
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        unit_401 = result["data"]["401"]
        assert unit_401["training"] == 0

    @pytest.mark.asyncio
    async def test_cancel_upgrade_success(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 취소: ready 복원 + upgrading 감소 + 자원 환불"""
        await setup_resources(fake_redis, test_user_no, food=1000)
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)

        resp = await call_api(client, test_user_no, 4003, {
            "unit_idx": 401, "target_unit_idx": 402, "quantity": 3
        })
        assert resp.json()["success"] is True

        # 취소
        resp = await call_api(client, test_user_no, 4005, {"unit_idx": 401})
        result = resp.json()
        assert result["success"] is True

        # info 조회 → ready=10 (복원), upgrading=0
        resp = await call_api(client, test_user_no, 4001)
        result = resp.json()
        unit_401 = result["data"]["401"]
        assert unit_401["ready"] == 10
        assert unit_401["upgrading"] == 0

    @pytest.mark.asyncio
    async def test_cancel_no_task(self, client, fake_redis, create_test_user, test_user_no):
        """유닛 존재하지만 진행 중인 작업 없이 cancel → 실패"""
        await setup_unit_in_cache(fake_redis, test_user_no, 401, total=10, ready=10)
        resp = await call_api(client, test_user_no, 4005, {"unit_idx": 401})
        result = resp.json()
        assert result["success"] is False
        assert "no task" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_cancel_invalid_unit(self, client, fake_redis, create_test_user, test_user_no):
        """존재하지 않는 unit_idx → 실패"""
        resp = await call_api(client, test_user_no, 4005, {"unit_idx": 999})
        result = resp.json()
        assert result["success"] is False


# ===========================================================================
# 4006 - 유닛 즉시 완료 (unit_speedup)
# ===========================================================================
class TestUnitSpeedup:
    @pytest.mark.asyncio
    async def test_speedup_success(self, client, fake_redis, create_test_user, test_user_no):
        """즉시 완료: completion_time이 과거로 변경됨"""
        await setup_resources(fake_redis, test_user_no)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        assert resp.json()["success"] is True

        # speedup
        resp = await call_api(client, test_user_no, 4006, {"unit_idx": 401})
        result = resp.json()
        assert result["success"] is True
        assert "accelerated" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_speedup_no_task(self, client, fake_redis, create_test_user, test_user_no):
        """진행 중인 작업 없이 speedup → 실패"""
        resp = await call_api(client, test_user_no, 4006, {"unit_idx": 401})
        result = resp.json()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_speedup_then_finish(self, client, fake_redis, create_test_user, test_user_no):
        """speedup → finish → training=0, ready=5"""
        await setup_resources(fake_redis, test_user_no)
        resp = await call_api(client, test_user_no, 4002, {"unit_idx": 401, "quantity": 5})
        assert resp.json()["success"] is True

        # speedup
        resp = await call_api(client, test_user_no, 4006, {"unit_idx": 401})
        assert resp.json()["success"] is True

        # finish
        resp = await call_api(client, test_user_no, 4004, {"unit_idx": 401, "unit_type": 0})
        result = resp.json()
        assert result["success"] is True

        # info 확인
        resp = await call_api(client, test_user_no, 4001)
        unit_401 = resp.json()["data"]["401"]
        assert unit_401["training"] == 0
        assert unit_401["ready"] == 5


# ===========================================================================
# 잘못된 API 코드
# ===========================================================================
class TestInvalidApiCode:
    @pytest.mark.asyncio
    async def test_unknown_api_code(self, client, fake_redis, create_test_user, test_user_no):
        """미등록 API 코드 → HTTP 400"""
        resp = await client.post("/api", json={
            "user_no": test_user_no,
            "api_code": 4999,
            "data": {}
        })
        assert resp.status_code == 400
