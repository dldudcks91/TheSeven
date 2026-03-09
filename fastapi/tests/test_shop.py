"""
상점 API 테스트
- 6011: 상점 정보 조회 (없으면 생성)
- 6012: 상점 새로고침
- 6013: 아이템 구매
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


async def seed_shop(fake_redis, user_no, item_indices=None, refresh_count=0):
    """테스트용 상점 데이터를 Redis에 직접 세팅"""
    from services.redis_manager.base_redis_cache_manager import BaseRedisCacheManager
    from services.redis_manager.redis_types import CacheType
    from datetime import datetime

    if item_indices is None:
        item_indices = [21001, 21002, 22001, 22002, 23001, 23002]

    slots = [
        {"slot": i, "item_idx": idx, "sold": False}
        for i, idx in enumerate(item_indices[:6])
    ]
    shop_data = {
        "slots": slots,
        "refresh_count": refresh_count,
        "last_refresh": datetime.utcnow().isoformat()
    }

    cache_mgr = BaseRedisCacheManager(fake_redis, CacheType.SHOP)
    hash_key = cache_mgr.get_user_data_hash_key(user_no)
    await fake_redis.hset(hash_key, "shop_data", json.dumps(shop_data))
    await fake_redis.expire(hash_key, 86400)
    return shop_data


# ===========================================================================
# 6011 - 상점 정보 조회
# ===========================================================================
class TestShopInfo:
    """상점 조회 API (6011) 테스트"""

    @pytest.mark.asyncio
    async def test_info_creates_new_shop(self, client, test_user_no):
        """상점 없을 때 → 새로 생성 후 반환 (6슬롯)"""
        result = await call_api(client, test_user_no, 6011)
        assert result["success"] is True
        slots = result["data"]["slots"]
        assert len(slots) == 6

    @pytest.mark.asyncio
    async def test_info_slot_structure(self, client, test_user_no):
        """슬롯 구조 확인: slot, item_idx, sold, item_info 포함"""
        result = await call_api(client, test_user_no, 6011)
        assert result["success"] is True
        slot = result["data"]["slots"][0]
        assert "slot" in slot
        assert "item_idx" in slot
        assert "sold" in slot
        assert "item_info" in slot

    @pytest.mark.asyncio
    async def test_info_returns_existing_shop(self, client, fake_redis, test_user_no):
        """기존 상점 데이터 있을 때 → 기존 데이터 반환"""
        await seed_shop(fake_redis, test_user_no, item_indices=[21001, 21002, 22001, 22002, 23001, 23002])
        result = await call_api(client, test_user_no, 6011)
        assert result["success"] is True
        item_idxs = [s["item_idx"] for s in result["data"]["slots"]]
        assert 21001 in item_idxs

    @pytest.mark.asyncio
    async def test_info_sold_false_on_new_shop(self, client, test_user_no):
        """새로 생성된 상점 → 모든 슬롯 sold=False"""
        result = await call_api(client, test_user_no, 6011)
        assert result["success"] is True
        for slot in result["data"]["slots"]:
            assert slot["sold"] is False

    @pytest.mark.asyncio
    async def test_info_refresh_count_zero(self, client, test_user_no):
        """새로 생성된 상점 → refresh_count=0"""
        result = await call_api(client, test_user_no, 6011)
        assert result["success"] is True
        assert result["data"]["refresh_count"] == 0

    @pytest.mark.asyncio
    async def test_info_idempotent(self, client, test_user_no):
        """두 번 조회해도 같은 아이템 반환 (새 상점 재생성 없음)"""
        first = await call_api(client, test_user_no, 6011)
        second = await call_api(client, test_user_no, 6011)
        assert first["success"] is True
        assert second["success"] is True
        first_items = sorted([s["item_idx"] for s in first["data"]["slots"]])
        second_items = sorted([s["item_idx"] for s in second["data"]["slots"]])
        assert first_items == second_items


# ===========================================================================
# 6012 - 상점 새로고침
# ===========================================================================
class TestShopRefresh:
    """상점 새로고침 API (6012) 테스트"""

    @pytest.mark.asyncio
    async def test_refresh_increments_count(self, client, fake_redis, test_user_no):
        """새로고침 → refresh_count 증가"""
        await seed_shop(fake_redis, test_user_no, refresh_count=0)
        result = await call_api(client, test_user_no, 6012)
        assert result["success"] is True
        assert result["data"]["refresh_count"] == 1

    @pytest.mark.asyncio
    async def test_refresh_resets_sold(self, client, fake_redis, test_user_no):
        """sold 슬롯이 있어도 새로고침 후 모두 sold=False"""
        shop = await seed_shop(fake_redis, test_user_no)
        # 슬롯 0 sold 처리
        shop["slots"][0]["sold"] = True
        from services.redis_manager.base_redis_cache_manager import BaseRedisCacheManager
        from services.redis_manager.redis_types import CacheType
        cache_mgr = BaseRedisCacheManager(fake_redis, CacheType.SHOP)
        hash_key = cache_mgr.get_user_data_hash_key(test_user_no)
        import json
        await fake_redis.hset(hash_key, "shop_data", json.dumps(shop))

        result = await call_api(client, test_user_no, 6012)
        assert result["success"] is True
        for slot in result["data"]["slots"]:
            assert slot["sold"] is False

    @pytest.mark.asyncio
    async def test_refresh_returns_6_slots(self, client, test_user_no):
        """새로고침 후에도 6슬롯 반환"""
        result = await call_api(client, test_user_no, 6012)
        assert result["success"] is True
        assert len(result["data"]["slots"]) == 6

    @pytest.mark.asyncio
    async def test_refresh_multiple_times(self, client, fake_redis, test_user_no):
        """여러 번 새로고침 → refresh_count 누적"""
        await seed_shop(fake_redis, test_user_no, refresh_count=2)
        result = await call_api(client, test_user_no, 6012)
        assert result["success"] is True
        assert result["data"]["refresh_count"] == 3


# ===========================================================================
# 6013 - 아이템 구매
# ===========================================================================
class TestShopBuy:
    """상점 구매 API (6013) 테스트"""

    @pytest.mark.asyncio
    async def test_buy_success(self, client, fake_redis, test_user_no):
        """정상 구매 → 아이템 인벤토리에 추가, slot sold=True"""
        await seed_shop(fake_redis, test_user_no, item_indices=[21001, 21002, 22001, 22002, 23001, 23002])
        result = await call_api(client, test_user_no, 6013, {"slot": 0})
        assert result["success"] is True
        assert result["data"]["slot"] == 0
        assert result["data"]["item_idx"] == 21001

    @pytest.mark.asyncio
    async def test_buy_adds_to_inventory(self, client, fake_redis, test_user_no):
        """구매 후 6001 조회 시 아이템 인벤토리에 반영"""
        await seed_shop(fake_redis, test_user_no, item_indices=[21001, 21002, 22001, 22002, 23001, 23002])
        await call_api(client, test_user_no, 6013, {"slot": 0})

        items = await call_api(client, test_user_no, 6001)
        assert items["success"] is True
        assert "21001" in items["data"]
        assert items["data"]["21001"]["quantity"] >= 1

    @pytest.mark.asyncio
    async def test_buy_marks_slot_sold(self, client, fake_redis, test_user_no):
        """구매 후 해당 슬롯 sold=True"""
        await seed_shop(fake_redis, test_user_no, item_indices=[21001, 21002, 22001, 22002, 23001, 23002])
        await call_api(client, test_user_no, 6013, {"slot": 0})

        shop = await call_api(client, test_user_no, 6011)
        slot_0 = next(s for s in shop["data"]["slots"] if s["slot"] == 0)
        assert slot_0["sold"] is True

    @pytest.mark.asyncio
    async def test_buy_already_sold(self, client, fake_redis, test_user_no):
        """이미 구매한 슬롯 재구매 → 실패"""
        await seed_shop(fake_redis, test_user_no, item_indices=[21001, 21002, 22001, 22002, 23001, 23002])
        await call_api(client, test_user_no, 6013, {"slot": 0})
        result = await call_api(client, test_user_no, 6013, {"slot": 0})
        assert result["success"] is False
        assert "already" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_buy_invalid_slot(self, client, fake_redis, test_user_no):
        """존재하지 않는 슬롯 번호 → 실패"""
        await seed_shop(fake_redis, test_user_no)
        result = await call_api(client, test_user_no, 6013, {"slot": 99})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_buy_missing_slot(self, client, test_user_no):
        """slot 파라미터 누락 → 실패"""
        result = await call_api(client, test_user_no, 6013, {})
        assert result["success"] is False  # data 자체가 비어있어 "Missing data" 반환

    @pytest.mark.asyncio
    async def test_buy_no_shop_data(self, client, test_user_no):
        """상점 데이터 없는 상태에서 구매 → 실패"""
        result = await call_api(client, test_user_no, 6013, {"slot": 0})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_buy_different_slots_independent(self, client, fake_redis, test_user_no):
        """슬롯 0 구매 후 슬롯 1은 여전히 구매 가능"""
        await seed_shop(fake_redis, test_user_no, item_indices=[21001, 21002, 22001, 22002, 23001, 23002])
        await call_api(client, test_user_no, 6013, {"slot": 0})
        result = await call_api(client, test_user_no, 6013, {"slot": 1})
        assert result["success"] is True
        assert result["data"]["item_idx"] == 21002
