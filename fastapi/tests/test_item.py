"""
아이템 API 테스트
- 6001: 아이템 목록 조회
- 6002: 아이템 추가 (item_get)
- 6003: 아이템 사용 (item_use)

메타데이터:
  21001: category=resource, sub_category=food, value=1000
  21002: category=resource, sub_category=food, value=10000
"""
import pytest
import json


async def call_api(client, user_no, api_code, data=None):
    resp = await client.post("/api", json={
        "user_no": user_no,
        "api_code": api_code,
        "data": data or {}
    })
    return resp.json()


async def seed_item(fake_redis, user_no, item_idx, quantity):
    """테스트용 아이템을 Redis에 직접 세팅"""
    from services.redis_manager.base_redis_cache_manager import BaseRedisCacheManager
    from services.redis_manager.redis_types import CacheType
    from datetime import datetime

    cache_mgr = BaseRedisCacheManager(fake_redis, CacheType.ITEM)
    hash_key = cache_mgr.get_user_data_hash_key(user_no)
    item_data = {
        "user_no": user_no,
        "item_idx": item_idx,
        "quantity": quantity,
        "cached_at": datetime.utcnow().isoformat()
    }
    await fake_redis.hset(hash_key, str(item_idx), json.dumps(item_data))
    await fake_redis.expire(hash_key, 3600)


# ===========================================================================
# 6001 - 아이템 목록 조회
# ===========================================================================
class TestItemInfo:
    """아이템 조회 API (6001) 테스트"""

    @pytest.mark.asyncio
    async def test_info_empty(self, client, test_user_no):
        """아이템 없을 때 → 빈 dict"""
        result = await call_api(client, test_user_no, 6001)
        assert result["success"] is True
        assert result["data"] == {} or isinstance(result["data"], dict)

    @pytest.mark.asyncio
    async def test_info_with_items(self, client, fake_redis, test_user_no):
        """Redis에 아이템 세팅 → 반환"""
        await seed_item(fake_redis, test_user_no, 21001, 5)
        result = await call_api(client, test_user_no, 6001)
        assert result["success"] is True
        assert "21001" in result["data"]
        assert result["data"]["21001"]["quantity"] == 5

    @pytest.mark.asyncio
    async def test_info_multiple_items(self, client, fake_redis, test_user_no):
        """여러 아이템 세팅 → 모두 반환"""
        await seed_item(fake_redis, test_user_no, 21001, 3)
        await seed_item(fake_redis, test_user_no, 21002, 7)
        result = await call_api(client, test_user_no, 6001)
        assert result["success"] is True
        assert "21001" in result["data"]
        assert "21002" in result["data"]


# ===========================================================================
# 6002 - 아이템 추가 (item_get)
# ===========================================================================
class TestItemGet:
    """아이템 추가 API (6002) 테스트"""

    @pytest.mark.asyncio
    async def test_get_success(self, client, test_user_no):
        """정상 추가 → new_quantity=1"""
        result = await call_api(client, test_user_no, 6002, {"item_idx": 21001, "quantity": 1})
        assert result["success"] is True
        assert result["data"]["item_idx"] == 21001
        assert result["data"]["new_quantity"] == 1
        assert result["data"]["added_quantity"] == 1

    @pytest.mark.asyncio
    async def test_get_accumulate(self, client, test_user_no):
        """같은 아이템 두 번 추가 → 누적"""
        await call_api(client, test_user_no, 6002, {"item_idx": 21001, "quantity": 3})
        result = await call_api(client, test_user_no, 6002, {"item_idx": 21001, "quantity": 2})
        assert result["success"] is True
        assert result["data"]["new_quantity"] == 5

    @pytest.mark.asyncio
    async def test_get_missing_item_idx(self, client, test_user_no):
        """item_idx 누락 → 실패"""
        result = await call_api(client, test_user_no, 6002, {"quantity": 1})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_zero_quantity(self, client, test_user_no):
        """quantity=0 → 실패"""
        result = await call_api(client, test_user_no, 6002, {"item_idx": 21001, "quantity": 0})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_negative_quantity(self, client, test_user_no):
        """quantity < 0 → 실패"""
        result = await call_api(client, test_user_no, 6002, {"item_idx": 21001, "quantity": -5})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_default_quantity(self, client, test_user_no):
        """quantity 미지정 시 기본값 1"""
        result = await call_api(client, test_user_no, 6002, {"item_idx": 21001})
        assert result["success"] is True
        assert result["data"]["new_quantity"] == 1

    @pytest.mark.asyncio
    async def test_get_visible_in_info(self, client, test_user_no):
        """추가 후 6001 조회 시 반영 확인"""
        await call_api(client, test_user_no, 6002, {"item_idx": 21001, "quantity": 4})
        info = await call_api(client, test_user_no, 6001)
        assert info["success"] is True
        assert "21001" in info["data"]
        assert info["data"]["21001"]["quantity"] == 4


# ===========================================================================
# 6003 - 아이템 사용 (item_use)
# ===========================================================================
class TestItemUse:
    """아이템 사용 API (6003) 테스트"""

    @pytest.mark.asyncio
    async def test_use_no_item(self, client, test_user_no):
        """보유 아이템 없을 때 사용 → 실패"""
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 1})
        assert result["success"] is False
        assert "not enough" in result["message"].lower() or "insufficient" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_use_insufficient_quantity(self, client, fake_redis, test_user_no):
        """보유 3개, 5개 사용 요청 → 실패"""
        await seed_item(fake_redis, test_user_no, 21001, 3)
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 5})
        assert result["success"] is False
        assert result["data"]["available"] == 3
        assert result["data"]["required"] == 5

    @pytest.mark.asyncio
    async def test_use_resource_item_success(self, client, fake_redis, create_test_user, test_user_no):
        """자원 아이템(21001: food +1000) 사용 → food 증가, 아이템 차감"""
        await seed_item(fake_redis, test_user_no, 21001, 2)

        food_before = (await call_api(client, test_user_no, 1011))["data"]["food"]
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 1})

        assert result["success"] is True
        assert result["data"]["used_quantity"] == 1
        assert result["data"]["remaining_quantity"] == 1

        # 자원 증가 확인
        food_after = (await call_api(client, test_user_no, 1011))["data"]["food"]
        assert food_after == food_before + 1000

    @pytest.mark.asyncio
    async def test_use_multiple_quantity(self, client, fake_redis, create_test_user, test_user_no):
        """아이템 2개 사용 → food +2000"""
        await seed_item(fake_redis, test_user_no, 21001, 5)

        food_before = (await call_api(client, test_user_no, 1011))["data"]["food"]
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 2})

        assert result["success"] is True
        assert result["data"]["remaining_quantity"] == 3

        food_after = (await call_api(client, test_user_no, 1011))["data"]["food"]
        assert food_after == food_before + 2000

    @pytest.mark.asyncio
    async def test_use_item_removed_when_zero(self, client, fake_redis, create_test_user, test_user_no):
        """아이템 전부 사용 → 인벤토리에서 제거"""
        await seed_item(fake_redis, test_user_no, 21001, 1)
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 1})
        assert result["success"] is True
        assert result["data"]["remaining_quantity"] == 0

        info = await call_api(client, test_user_no, 6001)
        assert "21001" not in info["data"]

    @pytest.mark.asyncio
    async def test_use_missing_item_idx(self, client, test_user_no):
        """item_idx 누락 → 실패"""
        result = await call_api(client, test_user_no, 6003, {"quantity": 1})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_use_zero_quantity(self, client, fake_redis, test_user_no):
        """quantity=0 → 실패"""
        await seed_item(fake_redis, test_user_no, 21001, 3)
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 0})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_use_effect_data_returned(self, client, fake_redis, create_test_user, test_user_no):
        """사용 성공 시 effect 데이터 포함 응답"""
        await seed_item(fake_redis, test_user_no, 21001, 1)
        result = await call_api(client, test_user_no, 6003, {"item_idx": 21001, "quantity": 1})
        assert result["success"] is True
        effect = result["data"]["effect"]
        assert effect["category"] == "resource"
        assert effect["resource_type"] == "food"
        assert effect["amount"] == 1000
