"""
자원 API 테스트
- 1011: 자원 정보 조회
"""
import pytest


async def call_api(client, user_no, api_code, data=None):
    resp = await client.post("/api", json={
        "user_no": user_no,
        "api_code": api_code,
        "data": data or {}
    })
    return resp.json()


# ===========================================================================
# 1011 - 자원 정보 조회
# ===========================================================================
class TestResourceInfo:
    """자원 조회 API (1011) 테스트"""

    @pytest.mark.asyncio
    async def test_info_no_user_returns_zeros(self, client, test_user_no):
        """DB에 유저 없음 → 0 값으로 반환 (ResourceManager 폴백 동작)"""
        result = await call_api(client, test_user_no, 1011)
        # DB 미스 시 0으로 초기화된 dict를 반환 → success: True
        assert result["success"] is True
        assert "food" in result["data"]
        assert result["data"]["food"] == 0

    @pytest.mark.asyncio
    async def test_info_with_user(self, client, create_test_user, test_user_no):
        """DB에 유저 존재 → 실제 자원 반환"""
        result = await call_api(client, test_user_no, 1011)
        assert result["success"] is True
        data = result["data"]
        for field in ["food", "wood", "stone", "gold", "ruby"]:
            assert field in data

    @pytest.mark.asyncio
    async def test_info_correct_initial_values(self, client, create_test_user, test_user_no):
        """초기 자원 값 확인 (conftest: food=100000, wood=100000 ...)"""
        result = await call_api(client, test_user_no, 1011)
        assert result["success"] is True
        assert result["data"]["food"] == 100000
        assert result["data"]["wood"] == 100000
        assert result["data"]["stone"] == 100000
        assert result["data"]["gold"] == 100000
        assert result["data"]["ruby"] == 1000

    @pytest.mark.asyncio
    async def test_info_redis_cache_hit(self, client, create_test_user, test_user_no):
        """두 번 조회해도 동일 값 반환 (Redis 캐시 히트)"""
        first = await call_api(client, test_user_no, 1011)
        second = await call_api(client, test_user_no, 1011)
        assert first["success"] is True
        assert second["success"] is True
        assert first["data"]["food"] == second["data"]["food"]

    @pytest.mark.asyncio
    async def test_info_after_resource_change(self, client, fake_redis, create_test_user, test_user_no):
        """자원 변경 후 조회 → 변경된 값 반영"""
        # 초기 조회 (DB → Redis 캐싱)
        before = await call_api(client, test_user_no, 1011)
        food_before = before["data"]["food"]

        # Redis에서 직접 food 차감 (building 생성 후 자원 변화 시뮬레이션)
        from services.redis_manager.resource_redis_manager import ResourceRedisManager
        from services.redis_manager.base_redis_cache_manager import BaseRedisCacheManager
        from services.redis_manager.redis_types import CacheType

        cache_mgr = BaseRedisCacheManager(fake_redis, CacheType.RESOURCES)
        hash_key = cache_mgr.get_user_data_hash_key(test_user_no)
        await fake_redis.hincrby(hash_key, "food", -500)

        after = await call_api(client, test_user_no, 1011)
        assert after["data"]["food"] == food_before - 500
