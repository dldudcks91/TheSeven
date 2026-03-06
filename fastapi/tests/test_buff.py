"""
버프 API 테스트
- 1012: 버프 정보 조회 (buff_info)
- Total Buffs 계산 검증
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
    return resp


async def setup_permanent_buff(fake_redis, user_no, target_type, source_key, buff_data):
    """
    영구 버프를 Redis에 직접 설정.
    Hash: user_data:{user_no}:buff → field=target_type, value=JSON({source_key: buff_data})
    """
    hash_key = f"user_data:{user_no}:buff"
    existing = await fake_redis.hget(hash_key, target_type)
    if existing:
        data = json.loads(existing)
    else:
        data = {}
    data[source_key] = buff_data
    await fake_redis.hset(hash_key, target_type, json.dumps(data, default=str))
    await fake_redis.expire(hash_key, 3600)


async def setup_temporary_buff(fake_redis, user_no, buff_id, metadata, duration_seconds=3600):
    """
    임시 버프를 Redis에 직접 설정.
    1. String: user:{user_no}:temp_buff:{buff_id} → JSON(metadata)
    2. Sorted Set: completion_queue:buff → member={user_no}:{buff_id}, score=만료시각
    """
    # 메타데이터 저장
    meta_key = f"user:{user_no}:temp_buff:{buff_id}"
    await fake_redis.setex(meta_key, duration_seconds, json.dumps(metadata, default=str))

    # 만료 큐 등록
    queue_key = "completion_queue:buff"
    member = f"{user_no}:{buff_id}"
    expiration = (datetime.utcnow() + timedelta(seconds=duration_seconds)).timestamp()
    await fake_redis.zadd(queue_key, {member: expiration})


# ===========================================================================
# 1012 - 버프 정보 조회 (buff_info)
# ===========================================================================
class TestBuffInfo:
    @pytest.mark.asyncio
    async def test_info_empty(self, client, fake_redis, create_test_user, test_user_no):
        """버프 없는 상태 → 빈 데이터"""
        resp = await call_api(client, test_user_no, 1012)
        result = resp.json()
        assert result["success"] is True
        assert result["data"]["permanent_buffs"] == {}
        assert result["data"]["temporary_buffs"] == []
        assert result["data"]["total_buffs"] == {}

    @pytest.mark.asyncio
    async def test_info_with_permanent_buff(self, client, fake_redis, create_test_user, test_user_no):
        """영구 버프 설정 → 정상 조회"""
        buff_data = {
            "buff_idx": 202,
            "target_type": "unit",
            "target_sub_type": "infantry",
            "stat_type": "attack",
            "value": 5,
            "value_type": "percentage"
        }
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:101_3", buff_data)

        resp = await call_api(client, test_user_no, 1012)
        result = resp.json()
        assert result["success"] is True

        perm = result["data"]["permanent_buffs"]
        assert "unit" in perm
        assert "research:101_3" in perm["unit"]
        assert perm["unit"]["research:101_3"]["buff_idx"] == 202
        assert perm["unit"]["research:101_3"]["value"] == 5

    @pytest.mark.asyncio
    async def test_info_with_temporary_buff(self, client, fake_redis, create_test_user, test_user_no):
        """임시 버프 설정 → 정상 조회"""
        metadata = {
            "buff_idx": 201,
            "target_type": "unit",
            "target_sub_type": "all",
            "stat_type": "speed",
            "value": 10,
            "value_type": "percentage",
            "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "source": "item"
        }
        await setup_temporary_buff(fake_redis, test_user_no, "test_buff_1", metadata)

        resp = await call_api(client, test_user_no, 1012)
        result = resp.json()
        assert result["success"] is True

        temp = result["data"]["temporary_buffs"]
        assert len(temp) == 1
        assert temp[0]["buff_idx"] == 201
        assert temp[0]["value"] == 10
        assert temp[0]["buff_id"] == "test_buff_1"

    @pytest.mark.asyncio
    async def test_info_total_sums_all_sources(self, client, fake_redis, create_test_user, test_user_no):
        """영구(5) + 임시(10) → total = 15"""
        perm_buff = {
            "buff_idx": 202,
            "target_type": "unit",
            "target_sub_type": "infantry",
            "stat_type": "attack",
            "value": 5,
            "value_type": "percentage"
        }
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:101_3", perm_buff)

        temp_meta = {
            "buff_idx": 202,
            "target_type": "unit",
            "target_sub_type": "infantry",
            "stat_type": "attack",
            "value": 10,
            "value_type": "percentage",
            "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "source": "item"
        }
        await setup_temporary_buff(fake_redis, test_user_no, "temp_atk", temp_meta)

        resp = await call_api(client, test_user_no, 1012)
        result = resp.json()
        assert result["success"] is True

        totals = result["data"]["total_buffs"]
        assert totals.get("unit:attack:infantry") == 15.0

    @pytest.mark.asyncio
    async def test_info_multiple_target_types(self, client, fake_redis, create_test_user, test_user_no):
        """unit + resource 버프 → 각각 분리 조회"""
        unit_buff = {
            "buff_idx": 202, "target_type": "unit", "target_sub_type": "infantry",
            "stat_type": "attack", "value": 5, "value_type": "percentage"
        }
        resource_buff = {
            "buff_idx": 101, "target_type": "resource", "target_sub_type": "all",
            "stat_type": "get", "value": 10, "value_type": "percentage"
        }
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:101_3", unit_buff)
        await setup_permanent_buff(fake_redis, test_user_no, "resource", "research:201_1", resource_buff)

        resp = await call_api(client, test_user_no, 1012)
        result = resp.json()

        perm = result["data"]["permanent_buffs"]
        assert "unit" in perm
        assert "resource" in perm

        totals = result["data"]["total_buffs"]
        assert totals.get("unit:attack:infantry") == 5.0
        assert totals.get("resource:get:all") == 10.0


# ===========================================================================
# Total Buffs 계산 검증
# ===========================================================================
class TestTotalBuffsCalculation:
    @pytest.mark.asyncio
    async def test_multiple_sources_same_key(self, client, fake_redis, create_test_user, test_user_no):
        """동일 stat 키에 여러 소스(5+3) → 합산 8"""
        buff1 = {
            "buff_idx": 202, "target_type": "unit", "target_sub_type": "infantry",
            "stat_type": "attack", "value": 5, "value_type": "percentage"
        }
        buff2 = {
            "buff_idx": 202, "target_type": "unit", "target_sub_type": "infantry",
            "stat_type": "attack", "value": 3, "value_type": "percentage"
        }
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:101_1", buff1)
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:101_2", buff2)

        resp = await call_api(client, test_user_no, 1012)
        totals = resp.json()["data"]["total_buffs"]
        assert totals.get("unit:attack:infantry") == 8.0

    @pytest.mark.asyncio
    async def test_sub_type_all_separate_key(self, client, fake_redis, create_test_user, test_user_no):
        """sub_type=all → unit:speed:all 키로 집계"""
        buff_all = {
            "buff_idx": 201, "target_type": "unit", "target_sub_type": "all",
            "stat_type": "speed", "value": 10, "value_type": "percentage"
        }
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:201_1", buff_all)

        resp = await call_api(client, test_user_no, 1012)
        totals = resp.json()["data"]["total_buffs"]
        assert totals.get("unit:speed:all") == 10.0

    @pytest.mark.asyncio
    async def test_multiple_temp_buffs_summed(self, client, fake_redis, create_test_user, test_user_no):
        """임시 버프 3개(5+5+5) → total = 15"""
        for i in range(3):
            meta = {
                "buff_idx": 201, "target_type": "unit", "target_sub_type": "all",
                "stat_type": "speed", "value": 5, "value_type": "percentage",
                "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
                "source": "item"
            }
            await setup_temporary_buff(fake_redis, test_user_no, f"speed_buff_{i}", meta)

        resp = await call_api(client, test_user_no, 1012)
        result = resp.json()
        assert len(result["data"]["temporary_buffs"]) == 3
        assert result["data"]["total_buffs"].get("unit:speed:all") == 15.0

    @pytest.mark.asyncio
    async def test_different_stat_types_independent(self, client, fake_redis, create_test_user, test_user_no):
        """attack과 speed → 별도 키로 독립 집계"""
        atk_buff = {
            "buff_idx": 202, "target_type": "unit", "target_sub_type": "infantry",
            "stat_type": "attack", "value": 5, "value_type": "percentage"
        }
        spd_buff = {
            "buff_idx": 201, "target_type": "unit", "target_sub_type": "all",
            "stat_type": "speed", "value": 10, "value_type": "percentage"
        }
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:101_3", atk_buff)
        await setup_permanent_buff(fake_redis, test_user_no, "unit", "research:201_1", spd_buff)

        resp = await call_api(client, test_user_no, 1012)
        totals = resp.json()["data"]["total_buffs"]
        assert totals.get("unit:attack:infantry") == 5.0
        assert totals.get("unit:speed:all") == 10.0
        # attack과 speed는 서로 영향 없음
        assert "unit:attack:all" not in totals


# ===========================================================================
# 잘못된 API 코드
# ===========================================================================
class TestInvalidBuffApiCode:
    @pytest.mark.asyncio
    async def test_unregistered_buff_total_api(self, client, fake_redis, create_test_user, test_user_no):
        """미등록 API 코드 1111 → HTTP 400 (buff_total_info 미등록)"""
        resp = await client.post("/api", json={
            "user_no": test_user_no,
            "api_code": 1111,
            "data": {}
        })
        assert resp.status_code == 400
