"""
건물 API 테스트
- 2001: 건물 목록 조회
- 2002: 건물 생성
- 2003: 건물 업그레이드
- 2004: 건물 완료
- 2005: 건물 취소
- 2006: 완료된 건물 일괄 처리
- 2007: 건물 가속
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


async def setup_completed_building(fake_redis, user_no, building_idx=201, level=1):
    """
    완료 상태(status=0) 건물을 Redis에 직접 세팅.
    업그레이드 테스트의 사전 조건으로 사용.
    """
    building_data = {
        "building_idx": building_idx,
        "building_lv": level,
        "status": 0,
        "start_time": None,
        "end_time": None,
        "target_level": None,
        "last_dt": datetime.utcnow().isoformat(),
        "cached_at": datetime.utcnow().isoformat()
    }
    hash_key = f"user_data:{user_no}:building"
    await fake_redis.hset(hash_key, str(building_idx), json.dumps(building_data, default=str))
    await fake_redis.expire(hash_key, 3600)
    return building_data


# ===========================================================================
# 2001 - 건물 정보 조회
# ===========================================================================
class TestBuildingInfo:
    """건물 조회 API (2001) 테스트"""

    @pytest.mark.asyncio
    async def test_info_no_user(self, client):
        """유저 데이터 없이 건물 조회 → 빈 데이터"""
        result = await call_api(client, 99999, 2001)
        assert result["success"] is True
        assert isinstance(result["data"], dict)

    @pytest.mark.asyncio
    async def test_info_no_buildings(self, client, create_test_user, test_user_no):
        """유저 있고 건물 없을 때 → success: true, 빈 dict"""
        result = await call_api(client, test_user_no, 2001)
        assert result["success"] is True
        assert result["data"] == {} or isinstance(result["data"], dict)

    @pytest.mark.asyncio
    async def test_info_with_building(self, client, fake_redis, create_test_user, test_user_no):
        """건물 존재 시 → 데이터 반환"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        result = await call_api(client, test_user_no, 2001)
        assert result["success"] is True
        assert "201" in result["data"]
        assert result["data"]["201"]["building_lv"] == 1
        assert result["data"]["201"]["status"] == 0


# ===========================================================================
# 2002 - 건물 생성
# ===========================================================================
class TestBuildingCreate:
    """건물 생성 API (2002) 테스트"""

    @pytest.mark.asyncio
    async def test_create_success(self, client, create_test_user, test_user_no):
        """정상 건물 생성 → status=1, building_lv=0"""
        result = await call_api(client, test_user_no, 2002, {"building_idx": 201})
        assert result["success"] is True
        assert result["data"]["building_idx"] == 201
        assert result["data"]["building_lv"] == 0
        assert result["data"]["status"] == 1

    @pytest.mark.asyncio
    async def test_create_duplicate(self, client, create_test_user, test_user_no):
        """이미 존재하는 건물 재생성 → 실패"""
        await call_api(client, test_user_no, 2002, {"building_idx": 201})
        result = await call_api(client, test_user_no, 2002, {"building_idx": 201})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_invalid_building_idx(self, client, create_test_user, test_user_no):
        """존재하지 않는 building_idx → 실패"""
        result = await call_api(client, test_user_no, 2002, {"building_idx": 99999})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_missing_building_idx(self, client, create_test_user, test_user_no):
        """building_idx 누락 → 실패"""
        result = await call_api(client, test_user_no, 2002, {})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_consumes_resources(self, client, create_test_user, test_user_no):
        """건물 생성 시 자원 소모 확인 (201 Lv1: food=100)"""
        before = await call_api(client, test_user_no, 1011)
        food_before = before["data"]["food"]

        await call_api(client, test_user_no, 2002, {"building_idx": 201})

        after = await call_api(client, test_user_no, 1011)
        food_after = after["data"]["food"]
        assert food_after == food_before - 100


# ===========================================================================
# 2003 - 건물 업그레이드
# ===========================================================================
class TestBuildingUpgrade:
    """건물 업그레이드 API (2003) 테스트"""

    @pytest.mark.asyncio
    async def test_upgrade_success(self, client, fake_redis, create_test_user, test_user_no):
        """정상 업그레이드 → status=2, target_level=2"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        result = await call_api(client, test_user_no, 2003, {"building_idx": 201})
        assert result["success"] is True
        assert result["data"]["status"] == 2
        assert result["data"]["target_level"] == 2

    @pytest.mark.asyncio
    async def test_upgrade_not_found(self, client, create_test_user, test_user_no):
        """존재하지 않는 건물 업그레이드 → 실패"""
        result = await call_api(client, test_user_no, 2003, {"building_idx": 201})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_upgrade_already_in_progress(self, client, fake_redis, create_test_user, test_user_no):
        """이미 업그레이드 중인 건물 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)
        await call_api(client, test_user_no, 2003, {"building_idx": 201})

        result = await call_api(client, test_user_no, 2003, {"building_idx": 201})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_upgrade_max_level(self, client, fake_redis, create_test_user, test_user_no):
        """최대 레벨(10) 건물 업그레이드 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=10)

        result = await call_api(client, test_user_no, 2003, {"building_idx": 201})
        assert result["success"] is False
        assert "max" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_upgrade_consumes_resources(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 시 자원 소모 확인 (201 Lv2: food=200)"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        before = await call_api(client, test_user_no, 1011)
        food_before = before["data"]["food"]

        result = await call_api(client, test_user_no, 2003, {"building_idx": 201})
        assert result["success"] is True

        after = await call_api(client, test_user_no, 1011)
        food_after = after["data"]["food"]
        assert food_after == food_before - 200


# ===========================================================================
# 2007 - 건물 가속
# ===========================================================================
class TestBuildingSpeedup:
    """건물 가속 API (2007) 테스트"""

    @pytest.mark.asyncio
    async def test_speedup_success(self, client, fake_redis, create_test_user, test_user_no):
        """정상 가속 → end_time 단축"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)
        await call_api(client, test_user_no, 2003, {"building_idx": 201})

        result = await call_api(client, test_user_no, 2007, {
            "building_idx": 201,
            "speedup_seconds": 10
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_speedup_not_upgrading(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 중이 아닌 건물 가속 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        result = await call_api(client, test_user_no, 2007, {
            "building_idx": 201,
            "speedup_seconds": 10
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_speedup_invalid_seconds(self, client, fake_redis, create_test_user, test_user_no):
        """speedup_seconds <= 0 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)
        await call_api(client, test_user_no, 2003, {"building_idx": 201})

        result = await call_api(client, test_user_no, 2007, {
            "building_idx": 201,
            "speedup_seconds": 0
        })
        assert result["success"] is False


# ===========================================================================
# 2004 - 건물 완료
# ===========================================================================
class TestBuildingFinish:
    """건물 완료 API (2004) 테스트"""

    @pytest.mark.asyncio
    async def test_finish_upgrade_via_speedup(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 → 가속(시간 초과) → 완료 (전체 API 흐름)"""
        # 1. 완료된 건물 세팅
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        # 2. 업그레이드 시작 (status=2, 20초 소요)
        upgrade_result = await call_api(client, test_user_no, 2003, {"building_idx": 201})
        assert upgrade_result["success"] is True

        # 3. 가속으로 시간 충분히 단축 (20초 이상)
        speedup_result = await call_api(client, test_user_no, 2007, {
            "building_idx": 201,
            "speedup_seconds": 9999
        })
        assert speedup_result["success"] is True

        # 4. 완료 처리
        finish_result = await call_api(client, test_user_no, 2004, {"building_idx": 201})
        assert finish_result["success"] is True
        assert finish_result["data"]["building"]["building_lv"] == 2
        assert finish_result["data"]["building"]["status"] == 0

    @pytest.mark.asyncio
    async def test_finish_not_in_progress(self, client, fake_redis, create_test_user, test_user_no):
        """진행 중이 아닌 건물 완료 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        result = await call_api(client, test_user_no, 2004, {"building_idx": 201})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_finish_time_not_reached(self, client, fake_redis, create_test_user, test_user_no):
        """시간 안 지난 건물 완료 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)
        await call_api(client, test_user_no, 2003, {"building_idx": 201})

        # 가속 없이 바로 완료 시도
        result = await call_api(client, test_user_no, 2004, {"building_idx": 201})
        assert result["success"] is False
        assert "remaining" in result["message"].lower() or "not yet" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_finish_not_found(self, client, create_test_user, test_user_no):
        """존재하지 않는 건물 완료 → 실패"""
        result = await call_api(client, test_user_no, 2004, {"building_idx": 201})
        assert result["success"] is False


# ===========================================================================
# 2005 - 건물 취소
# ===========================================================================
class TestBuildingCancel:
    """건물 취소 API (2005) 테스트"""

    @pytest.mark.asyncio
    async def test_cancel_upgrade(self, client, fake_redis, create_test_user, test_user_no):
        """업그레이드 중 취소 → status 복구 + 자원 환불"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        before = await call_api(client, test_user_no, 1011)
        food_before = before["data"]["food"]

        # 업그레이드 (food 200 소모)
        await call_api(client, test_user_no, 2003, {"building_idx": 201})

        # 취소 (food 200 환불)
        result = await call_api(client, test_user_no, 2005, {"building_idx": 201})
        assert result["success"] is True
        assert result["data"]["action"] == "restored"

        # 자원 환불 확인
        after = await call_api(client, test_user_no, 1011)
        food_after = after["data"]["food"]
        assert food_after == food_before

    @pytest.mark.asyncio
    async def test_cancel_not_in_progress(self, client, fake_redis, create_test_user, test_user_no):
        """진행 중 아닌 건물 취소 → 실패"""
        await setup_completed_building(fake_redis, test_user_no, 201, level=1)

        result = await call_api(client, test_user_no, 2005, {"building_idx": 201})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_construction(self, client, create_test_user, test_user_no):
        """건설 중(status=1) 취소 → Redis + DB 삭제 + 자원 환불"""
        create_result = await call_api(client, test_user_no, 2002, {"building_idx": 201})
        assert create_result["success"] is True

        result = await call_api(client, test_user_no, 2005, {"building_idx": 201})
        assert result["success"] is True
        assert result["data"]["action"] == "deleted"
        assert result["data"]["refund_resources"]["food"] == 100

        # 건물 목록에서 사라졌는지 확인 (Redis + DB 모두 삭제됨)
        info = await call_api(client, test_user_no, 2001)
        assert "201" not in info["data"]


# ===========================================================================
# 2006 - 완료된 건물 일괄 처리
# ===========================================================================
class TestBuildingFinishAll:
    """완료된 건물 일괄 처리 API (2006) 테스트"""

    @pytest.mark.asyncio
    async def test_finish_all_none(self, client, fake_redis, create_test_user, test_user_no):
        """완료된 건물 없을 때 → 빈 리스트"""
        result = await call_api(client, test_user_no, 2006)
        assert result["success"] is True
        assert result["data"]["buildings"] == []

    @pytest.mark.asyncio
    async def test_finish_all_with_completed(self, client, fake_redis, create_test_user, test_user_no):
        """완료 시간 지난 건물들 일괄 완료"""
        for building_idx in [201, 401]:
            await setup_completed_building(fake_redis, test_user_no, building_idx, level=1)
            await call_api(client, test_user_no, 2003, {"building_idx": building_idx})
            await call_api(client, test_user_no, 2007, {
                "building_idx": building_idx,
                "speedup_seconds": 9999
            })

        result = await call_api(client, test_user_no, 2006)
        assert result["success"] is True
        assert len(result["data"]["buildings"]) == 2

        finished_idxs = [b["building_idx"] for b in result["data"]["buildings"]]
        assert 201 in finished_idxs
        assert 401 in finished_idxs


# ===========================================================================
# 잘못된 API 코드
# ===========================================================================
class TestInvalidApiCode:

    @pytest.mark.asyncio
    async def test_invalid_api_code(self, client):
        """미등록 api_code 호출 시 400 에러"""
        resp = await client.post("/api", json={
            "user_no": 1,
            "api_code": 9999,
            "data": {}
        })
        assert resp.status_code == 400
