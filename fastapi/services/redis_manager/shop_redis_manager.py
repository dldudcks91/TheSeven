from datetime import datetime
from typing import Optional, Dict, Any, List
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType
import logging
import random


class ShopRedisManager:
    """
    상점 전용 Redis 관리자
    
    저장 구조:
        user:{user_no}:shop (String/JSON):
            {
                "slots": [
                    {"slot": 0, "item_idx": 21001, "sold": False},
                    {"slot": 1, "item_idx": 31002, "sold": False},
                    ...
                ],
                "refresh_count": 0,
                "last_refresh": "2025-01-08T12:00:00Z"
            }
    """
    
    SLOT_COUNT = 6  # 상점 슬롯 수
    
    def __init__(self, redis_client):
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.SHOP)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.cache_expire_time = 86400  # 24시간

    def _get_shop_key(self, user_no: int) -> str:
        return f"user:{user_no}:shop"

    # ==================== 상점 데이터 ====================

    async def get_shop_data(self, user_no: int) -> Optional[Dict[str, Any]]:
        """
        상점 데이터 조회
        
        Returns:
            None if not exists
            {
                "slots": [...],
                "refresh_count": 0,
                "last_refresh": "..."
            }
        """
        try:
            shop_key = self._get_shop_key(user_no)
            data = await self.cache_manager.get_data(shop_key)
            
            if data:
                self.logger.debug(f"Shop data found for user {user_no}")
                return data
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting shop data: {e}")
            return None

    async def set_shop_data(self, user_no: int, shop_data: Dict[str, Any]) -> bool:
        """상점 데이터 저장"""
        try:
            shop_key = self._get_shop_key(user_no)
            success = await self.cache_manager.set_data(
                shop_key, shop_data, expire_time=self.cache_expire_time
            )
            
            if success:
                self.logger.debug(f"Shop data saved for user {user_no}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error setting shop data: {e}")
            return False

    async def create_shop_data(self, user_no: int, item_indices: List[int]) -> Dict[str, Any]:
        """
        새 상점 데이터 생성
        
        Args:
            item_indices: 상점에 표시할 아이템 인덱스 리스트
        """
        try:
            slots = []
            for i, item_idx in enumerate(item_indices[:self.SLOT_COUNT]):
                slots.append({
                    "slot": i,
                    "item_idx": item_idx,
                    "sold": False
                })
            
            shop_data = {
                "slots": slots,
                "refresh_count": 0,
                "last_refresh": datetime.utcnow().isoformat()
            }
            
            await self.set_shop_data(user_no, shop_data)
            
            self.logger.info(f"Created new shop for user {user_no} with {len(slots)} items")
            return shop_data
            
        except Exception as e:
            self.logger.error(f"Error creating shop data: {e}")
            return {}

    async def refresh_shop(self, user_no: int, item_indices: List[int]) -> Dict[str, Any]:
        """
        상점 새로고침 (아이템 랜덤 교체)
        
        Args:
            item_indices: 새로 표시할 아이템 인덱스 리스트
        """
        try:
            # 기존 데이터 조회
            existing = await self.get_shop_data(user_no)
            refresh_count = 0
            if existing:
                refresh_count = existing.get("refresh_count", 0) + 1
            
            # 새 슬롯 생성
            slots = []
            for i, item_idx in enumerate(item_indices[:self.SLOT_COUNT]):
                slots.append({
                    "slot": i,
                    "item_idx": item_idx,
                    "sold": False
                })
            
            shop_data = {
                "slots": slots,
                "refresh_count": refresh_count,
                "last_refresh": datetime.utcnow().isoformat()
            }
            
            await self.set_shop_data(user_no, shop_data)
            
            self.logger.info(f"Refreshed shop for user {user_no}, count={refresh_count}")
            return shop_data
            
        except Exception as e:
            self.logger.error(f"Error refreshing shop: {e}")
            return {}

    async def mark_slot_sold(self, user_no: int, slot: int) -> bool:
        """슬롯 구매 완료 표시"""
        try:
            shop_data = await self.get_shop_data(user_no)
            if not shop_data:
                return False
            
            slots = shop_data.get("slots", [])
            
            for s in slots:
                if s.get("slot") == slot:
                    s["sold"] = True
                    break
            
            shop_data["slots"] = slots
            await self.set_shop_data(user_no, shop_data)
            
            self.logger.debug(f"Marked slot {slot} as sold for user {user_no}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error marking slot sold: {e}")
            return False

    async def get_slot_info(self, user_no: int, slot: int) -> Optional[Dict[str, Any]]:
        """특정 슬롯 정보 조회"""
        try:
            shop_data = await self.get_shop_data(user_no)
            if not shop_data:
                return None
            
            for s in shop_data.get("slots", []):
                if s.get("slot") == slot:
                    return s
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting slot info: {e}")
            return None

    async def invalidate_shop(self, user_no: int) -> bool:
        """상점 데이터 삭제"""
        try:
            shop_key = self._get_shop_key(user_no)
            return await self.cache_manager.delete_data(shop_key)
        except Exception as e:
            self.logger.error(f"Error invalidating shop: {e}")
            return False