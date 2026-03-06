"""
연구 API 테스트
- 3001: 연구 목록 조회
- 3002: 연구 시작
- 3003: 연구 완료
- 3004: 연구 취소
"""
import pytest
import json
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------
async def call_api(client, user_no, api_code, data=None):
    """API 호출 단축 함수"""
    resp = await client.post("/api", json={
        "user_no": user_no,
        "api_code": api_code,
        "data": data or {}
    })
    return resp.json()


async def setup_resources(fake_redis, user_no, food=100000, wood=100000, stone=100000, gold=100000):
    """Redis에 자원 세팅"""
    hash_key = f"user_data:{user_no}:resources"
    await fake_redis.hset(hash_key, mapping={
        "food": str(food),
        "wood": str(wood),
        "stone": str(stone),
        "gold": str(gold),
    })
    await fake_redis.expire(hash_key, 3600)


async def setup_processing_research(fake_redis, user_no, research_idx=1001, research_lv=0, seconds_remaining=100):
    """
    진행 중(status=1) 연구를 Redis에 직접 세팅.
    완료/취소 테스트의 사전 조건으로 사용.
    """
    now = datetime.utcnow()
    end_time = now + timedelta(seconds=seconds_remaining)

    research_data = {
        "user_no": user_no,
        "research_idx": research_idx,
        "research_lv": research_lv,
        "status": 1,  # PROCESSING
        "start_time": now.isoformat(),
        "end_time": end_time.isoformat(),
        "last_dt": now.isoformat(),
        "cached_at": now.isoformat()
    }

    # 연구 캐시 해시에 저장
    hash_key = f"user_data:{user_no}:research"
    await fake_redis.hset(hash_key, str(research_idx), json.dumps(research_data, default=str))
    await fake_redis.expire(hash_key, 3600)

    # 완료 큐에 추가 (sorted set)
    member = f"{user_no}:{research_idx}"
    await fake_redis.zadd("completion_queue:research", {member: end_time.timestamp()})

    # 진행 중인 연구 설정 (O(1) 조회용)
    ongoing_key = f"user_data:{user_no}:research_ongoing"
    ongoing_data = json.dumps({
        "research_idx": research_idx,
        "end_time": end_time.isoformat()
    })
    await fake_redis.set(ongoing_key, ongoing_data)
    await fake_redis.expire(ongoing_key, 3600)

    return research_data


async def setup_completed_research(fake_redis, user_no, research_idx=1001, research_lv=1):
    """
    완료 상태(status=0) 연구를 Redis에 직접 세팅.
    """
    now = datetime.utcnow()
    research_data = {
        "user_no": user_no,
        "research_idx": research_idx,
        "research_lv": research_lv,
        "status": 0,  # COMPLETED
        "start_time": None,
        "end_time": None,
        "last_dt": now.isoformat(),
        "cached_at": now.isoformat()
    }

    hash_key = f"user_data:{user_no}:research"
    await fake_redis.hset(hash_key, str(research_idx), json.dumps(research_data, default=str))
    await fake_redis.expire(hash_key, 3600)
    return research_data


async def setup_past_research(fake_redis, user_no, research_idx=1001, research_lv=0):
    """
    완료 시간이 이미 지난 진행 중 연구를 Redis에 세팅.
    research_finish 테스트용.
    """
    now = datetime.utcnow()
    end_time = now - timedelta(seconds=10)  # 10초 전에 이미 완료

    research_data = {
        "user_no": user_no,
        "research_idx": research_idx,
        "research_lv": research_lv,
        "status": 1,  # PROCESSING
        "start_time": (now - timedelta(seconds=30)).isoformat(),
        "end_time": end_time.isoformat(),
        "last_dt": now.isoformat(),
        "cached_at": now.isoformat()
    }

    hash_key = f"user_data:{user_no}:research"
    await fake_redis.hset(hash_key, str(research_idx), json.dumps(research_data, default=str))
    await fake_redis.expire(hash_key, 3600)

    # 완료 큐
    member = f"{user_no}:{research_idx}"
    await fake_redis.zadd("completion_queue:research", {member: end_time.timestamp()})

    # 진행 중인 연구
    ongoing_key = f"user_data:{user_no}:research_ongoing"
    ongoing_data = json.dumps({
        "research_idx": research_idx,
        "end_time": end_time.isoformat()
    })
    await fake_redis.set(ongoing_key, ongoing_data)
    await fake_redis.expire(ongoing_key, 3600)

    return research_data


# ===========================================================================
# 3001: 연구 목록 조회
# ===========================================================================
class TestResearchInfo:
    """연구 정보 조회 API (3001) 테스트"""

    @pytest.mark.asyncio
    async def test_info_empty(self, client, fake_redis, create_test_user, test_user_no):
        """연구 데이터 없는 초기 상태 → 빈 목록"""
        result = await call_api(client, test_user_no, 3001)
        assert result["success"] is True
        assert isinstance(result["data"], dict)

    @pytest.mark.asyncio
    async def test_info_with_data(self, client, fake_redis, create_test_user, test_user_no):
        """Redis에 연구 데이터 존재 시 정상 조회"""
        await setup_completed_research(fake_redis, test_user_no, 1001, research_lv=1)
        result = await call_api(client, test_user_no, 3001)
        assert result["success"] is True
        assert "1001" in result["data"]
        assert result["data"]["1001"]["status"] == 0  # COMPLETED


# ===========================================================================
# 3002: 연구 시작
# ===========================================================================
class TestResearchStart:
    """연구 시작 API (3002) 테스트"""

    @pytest.mark.asyncio
    async def test_start_success(self, client, fake_redis, create_test_user, test_user_no):
        """
        정상 연구 시작: research_idx=1001, lv=1
        CSV 기준: food=100, gold=100, time=20s
        """
        await setup_resources(fake_redis, test_user_no, food=1000, gold=1000)

        result = await call_api(client, test_user_no, 3002, {
            "research_idx": 1001,
            "research_lv": 1
        })
        assert result["success"] is True
        assert result["data"]["status"] == 1  # PROCESSING
        assert result["data"]["end_time"] is not None

        # 자원 차감 확인 (food 100, gold 100)
        food = await fake_redis.hget(f"user_data:{test_user_no}:resources", "food")
        gold = await fake_redis.hget(f"user_data:{test_user_no}:resources", "gold")
        assert int(food) == 900
        assert int(gold) == 900

    @pytest.mark.asyncio
    async def test_start_insufficient_resources(self, client, fake_redis, create_test_user, test_user_no):
        """자원 부족 시 실패"""
        await setup_resources(fake_redis, test_user_no, food=10, gold=10)

        result = await call_api(client, test_user_no, 3002, {
            "research_idx": 1001,
            "research_lv": 1
        })
        assert result["success"] is False
        assert "Resource" in result["message"] or "resource" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_start_duplicate(self, client, fake_redis, create_test_user, test_user_no):
        """이미 진행 중인 연구가 있을 때 거부"""
        await setup_resources(fake_redis, test_user_no)
        await setup_processing_research(fake_redis, test_user_no, 1001)

        result = await call_api(client, test_user_no, 3002, {
            "research_idx": 2001,
            "research_lv": 1
        })
        assert result["success"] is False
        assert "already" in result["message"].lower() or "progress" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_start_missing_params(self, client, fake_redis, create_test_user, test_user_no):
        """필수 파라미터 누락"""
        # research_idx 누락
        result = await call_api(client, test_user_no, 3002, {})
        assert result["success"] is False

        # research_lv 누락
        result2 = await call_api(client, test_user_no, 3002, {
            "research_idx": 1001
        })
        assert result2["success"] is False

    @pytest.mark.asyncio
    async def test_start_invalid_config(self, client, fake_redis, create_test_user, test_user_no):
        """존재하지 않는 연구 idx/lv → 실패"""
        await setup_resources(fake_redis, test_user_no)
        result = await call_api(client, test_user_no, 3002, {
            "research_idx": 99999,
            "research_lv": 1
        })
        assert result["success"] is False


# ===========================================================================
# 3003: 연구 완료
# ===========================================================================
class TestResearchFinish:
    """연구 완료 API (3003) 테스트"""

    @pytest.mark.asyncio
    async def test_finish_success(self, client, fake_redis, create_test_user, test_user_no):
        """완료 시간이 지난 연구 → 정상 완료, 레벨 증가"""
        await setup_past_research(fake_redis, test_user_no, 1001, research_lv=0)

        result = await call_api(client, test_user_no, 3003, {
            "research_idx": 1001
        })
        assert result["success"] is True
        research = result["data"]["research"]
        assert research["status"] == 0  # COMPLETED
        assert research["research_lv"] == 1  # 0 → 1

    @pytest.mark.asyncio
    async def test_finish_not_ready(self, client, fake_redis, create_test_user, test_user_no):
        """완료 시간 미경과 → 실패"""
        await setup_processing_research(fake_redis, test_user_no, 1001, seconds_remaining=9999)

        result = await call_api(client, test_user_no, 3003, {
            "research_idx": 1001
        })
        assert result["success"] is False
        assert "remaining" in result["message"].lower() or "not yet" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_finish_not_processing(self, client, fake_redis, create_test_user, test_user_no):
        """진행 중이 아닌 연구 완료 시도 → 실패"""
        await setup_completed_research(fake_redis, test_user_no, 1001, research_lv=1)

        result = await call_api(client, test_user_no, 3003, {
            "research_idx": 1001
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_finish_nonexistent(self, client, fake_redis, create_test_user, test_user_no):
        """존재하지 않는 연구 완료 시도 → 실패"""
        result = await call_api(client, test_user_no, 3003, {
            "research_idx": 99999
        })
        assert result["success"] is False


# ===========================================================================
# 3004: 연구 취소
# ===========================================================================
class TestResearchCancel:
    """연구 취소 API (3004) 테스트"""

    @pytest.mark.asyncio
    async def test_cancel_success(self, client, fake_redis, create_test_user, test_user_no):
        """
        진행 중인 연구 취소 → 50% 자원 환불
        research 1001 Lv1 cost: food=100, gold=100
        환불: food=50, gold=50
        """
        # 자원을 0으로 세팅 (시작 시 차감된 상태)
        await setup_resources(fake_redis, test_user_no, food=0, gold=0)
        await setup_processing_research(fake_redis, test_user_no, 1001, research_lv=0)

        result = await call_api(client, test_user_no, 3004, {
            "research_idx": 1001
        })
        assert result["success"] is True
        assert "refund" in result["data"] or "refunded" in result["data"]

        # 환불된 자원 확인
        refunded = result["data"].get("refunded", {})
        assert refunded.get("food", 0) == 50
        assert refunded.get("gold", 0) == 50

        # Redis 자원 확인
        food = await fake_redis.hget(f"user_data:{test_user_no}:resources", "food")
        gold = await fake_redis.hget(f"user_data:{test_user_no}:resources", "gold")
        assert int(food) == 50
        assert int(gold) == 50

    @pytest.mark.asyncio
    async def test_cancel_not_processing(self, client, fake_redis, create_test_user, test_user_no):
        """진행 중이 아닌 연구 취소 → 실패"""
        await setup_completed_research(fake_redis, test_user_no, 1001)

        result = await call_api(client, test_user_no, 3004, {
            "research_idx": 1001
        })
        assert result["success"] is False


# ===========================================================================
# 통합 플로우 테스트
# ===========================================================================
class TestResearchFlow:
    """연구 API 통합 플로우 테스트"""

    @pytest.mark.asyncio
    async def test_full_flow_start_to_finish(self, client, fake_redis, create_test_user, test_user_no):
        """
        전체 플로우: 시작(3002) → 완료(3003)
        시작 후 end_time을 과거로 수정하여 즉시 완료 가능하게 만듦
        """
        await setup_resources(fake_redis, test_user_no, food=1000, gold=1000)

        # 1. 연구 시작
        start_result = await call_api(client, test_user_no, 3002, {
            "research_idx": 1001,
            "research_lv": 1
        })
        assert start_result["success"] is True

        # 2. end_time을 과거로 수정 (시간 경과 시뮬레이션)
        hash_key = f"user_data:{test_user_no}:research"
        raw = await fake_redis.hget(hash_key, "1001")
        research_data = json.loads(raw)
        past_time = (datetime.utcnow() - timedelta(seconds=10)).isoformat()
        research_data["end_time"] = past_time
        await fake_redis.hset(hash_key, "1001", json.dumps(research_data, default=str))

        # 완료 큐의 score도 과거로 수정
        member = f"{test_user_no}:1001"
        past_ts = (datetime.utcnow() - timedelta(seconds=10)).timestamp()
        await fake_redis.zadd("completion_queue:research", {member: past_ts})

        # 3. 연구 완료
        finish_result = await call_api(client, test_user_no, 3003, {
            "research_idx": 1001
        })
        assert finish_result["success"] is True
        assert finish_result["data"]["research"]["status"] == 0
        assert finish_result["data"]["research"]["research_lv"] == 1

    @pytest.mark.asyncio
    async def test_start_cancel_restart(self, client, fake_redis, create_test_user, test_user_no):
        """
        시작(3002) → 취소(3004) → 재시작(3002)
        취소 후 다시 연구 시작 가능한지 검증
        """
        await setup_resources(fake_redis, test_user_no, food=10000, gold=10000)

        # 1. 연구 시작
        start1 = await call_api(client, test_user_no, 3002, {
            "research_idx": 1001,
            "research_lv": 1
        })
        assert start1["success"] is True

        # 2. 취소
        cancel = await call_api(client, test_user_no, 3004, {
            "research_idx": 1001
        })
        assert cancel["success"] is True

        # 3. 재시작
        start2 = await call_api(client, test_user_no, 3002, {
            "research_idx": 1001,
            "research_lv": 1
        })
        assert start2["success"] is True
        assert start2["data"]["status"] == 1  # PROCESSING


# ===========================================================================
# 잘못된 API 코드
# ===========================================================================
class TestInvalidApiCode:
    @pytest.mark.asyncio
    async def test_unknown_api_code(self, client, fake_redis, create_test_user, test_user_no):
        """미등록 API 코드 → HTTP 400"""
        resp = await client.post("/api", json={
            "user_no": test_user_no,
            "api_code": 3999,
            "data": {}
        })
        assert resp.status_code == 400
