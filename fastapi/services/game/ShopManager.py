from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from services.game import ItemManager
from datetime import datetime
import logging
import random
from typing import Dict, Any, List


class ShopManager:
    """
    상점 관리자
    
    기능:
        - Shop_info: 상점 정보 조회 (없으면 생성)
        - Shop_refresh: 상점 새로고침 (아이템 랜덤 교체)
        - Shop_buy: 아이템 구매
    
    데이터 구조:
        {
            "slots": [
                {"slot": 0, "item_idx": 21001, "sold": False},
                ...
            ],
            "refresh_count": 0,
            "last_refresh": "2025-01-08T12:00:00Z"
        }
    """
    
    CONFIG_TYPE = 'shop'
    SLOT_COUNT = 6
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.redis_manager = redis_manager
        self.db_manager = db_manager
        self.shop_redis = redis_manager.get_shop_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value

    def _get_random_items(self, count: int = SLOT_COUNT) -> List[int]:
        """weight 기반으로 상점 아이템 랜덤 선택 (중복 없이)"""
        try:
            shop_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
            
            if not shop_configs:
                self.logger.warning("No shop configs found")
                return []
            
            items = list(shop_configs.keys())
            weights = [shop_configs[idx].get('weight', 1) for idx in items]
            
            if len(items) <= count:
                return items
            
            # 중복 없이 weight 기반 선택
            selected = []
            for _ in range(count):
                chosen = random.choices(items, weights=weights, k=1)[0]
                selected.append(chosen)
                
                # 제거
                i = items.index(chosen)
                items.pop(i)
                weights.pop(i)
            
            return selected
        
        except Exception as e:
            self.logger.error(f"Error getting random items: {e}")
            return []

    def _get_item_detail(self, item_idx: int) -> Dict[str, Any]:
        """아이템 메타데이터 조회"""
        try:
            item_configs = GameDataManager.REQUIRE_CONFIGS.get("item", {})
            config = item_configs.get(item_idx, {})
            
            return {
                "item_idx": item_idx,
                "category": config.get("category", ""),
                "sub_category": config.get("sub_category", ""),
                "value": config.get("value", 0),
                "english_name": config.get("english_name", ""),
                "korean_name": config.get("korean_name", ""),
                "price": 0,  # 무료
                "price_type": "free"
            }
        except Exception as e:
            self.logger.error(f"Error getting item detail: {e}")
            return {"item_idx": item_idx}

    # ==================== API 메서드 ====================

    async def shop_info(self) -> Dict[str, Any]:
        """
        API: 상점 정보 조회
        
        - 상점 데이터가 없으면 새로 생성
        - 슬롯별 아이템 메타데이터 포함
        
        Returns:
            {
                "success": True,
                "data": {
                    "slots": [
                        {
                            "slot": 0,
                            "item_idx": 21001,
                            "sold": False,
                            "item_info": {...}
                        },
                        ...
                    ],
                    "refresh_count": 0,
                    "last_refresh": "..."
                }
            }
        """
        user_no = self.user_no
        
        try:
            # 1. 기존 상점 데이터 조회
            shop_data = await self.shop_redis.get_shop_data(user_no)
            
            # 2. 없으면 새로 생성
            if not shop_data:
                self.logger.info(f"Creating new shop for user {user_no}")
                random_items = self._get_random_items()
                shop_data = await self.shop_redis.create_shop_data(user_no, random_items)
            
            # 3. 슬롯에 아이템 메타데이터 추가
            enriched_slots = []
            for slot in shop_data.get("slots", []):
                item_idx = slot.get("item_idx")
                enriched_slot = {
                    **slot,
                    "item_info": self._get_item_detail(item_idx)
                }
                enriched_slots.append(enriched_slot)
            
            return {
                "success": True,
                "data": {
                    "slots": enriched_slots,
                    "refresh_count": shop_data.get("refresh_count", 0),
                    "last_refresh": shop_data.get("last_refresh", "")
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in shop_info: {e}")
            return {"success": False, "message": str(e)}

    async def shop_refresh(self) -> Dict[str, Any]:
        """
        API: 상점 새로고침
        
        - 모든 슬롯의 아이템을 랜덤으로 교체
        - sold 상태 초기화
        
        Returns:
            {
                "success": True,
                "data": {
                    "slots": [...],
                    "refresh_count": 1,
                    "last_refresh": "..."
                }
            }
        """
        user_no = self.user_no
        
        try:
            # 1. 새 랜덤 아이템 선택
            random_items = self._get_random_items()
            
            # 2. 상점 새로고침
            shop_data = await self.shop_redis.refresh_shop(user_no, random_items)
            
            if not shop_data:
                return {"success": False, "message": "Failed to refresh shop"}
            
            # 3. 슬롯에 아이템 메타데이터 추가
            enriched_slots = []
            for slot in shop_data.get("slots", []):
                item_idx = slot.get("item_idx")
                enriched_slot = {
                    **slot,
                    "item_info": self._get_item_detail(item_idx)
                }
                enriched_slots.append(enriched_slot)
            
            self.logger.info(f"Shop refreshed for user {user_no}")
            
            return {
                "success": True,
                "data": {
                    "slots": enriched_slots,
                    "refresh_count": shop_data.get("refresh_count", 0),
                    "last_refresh": shop_data.get("last_refresh", "")
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in shop_refresh: {e}")
            return {"success": False, "message": str(e)}

    async def shop_buy(self) -> Dict[str, Any]:
        """
        API: 아이템 구매
        
        Request data:
            {"slot": 0}  # 구매할 슬롯 번호
        
        Returns:
            {
                "success": True,
                "data": {
                    "slot": 0,
                    "item_idx": 21001,
                    "item_info": {...}
                }
            }
        """
        user_no = self.user_no
        
        try:
            # 1. 입력값 검증
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            slot = self._data.get("slot")
            if slot is None:
                return {"success": False, "message": "Missing slot number"}
            
            # 2. 슬롯 정보 조회
            slot_info = await self.shop_redis.get_slot_info(user_no, slot)
            
            if not slot_info:
                return {"success": False, "message": f"Slot {slot} not found"}
            
            # 3. 이미 구매했는지 확인
            if slot_info.get("sold"):
                return {"success": False, "message": "Already purchased"}
            
            item_idx = slot_info.get("item_idx")
            
            # 4. 아이템 추가 (ItemManager 사용)
            
            item_manager = ItemManager(self.db_manager, self.redis_manager)
            item_manager.user_no = user_no
            item_manager.data = {"item_idx": item_idx, "quantity": 1}
            
            add_result = await item_manager.add_item()
            
            if not add_result.get("success"):
                return {
                    "success": False,
                    "message": f"Failed to add item: {add_result.get('message')}"
                }
            
            # 5. 슬롯 sold 표시
            await self.shop_redis.mark_slot_sold(user_no, slot)
            
            self.logger.info(f"User {user_no} purchased item {item_idx} from slot {slot}")
            
            return {
                "success": True,
                "data": {
                    "slot": slot,
                    "item_idx": item_idx,
                    "item_info": self._get_item_detail(item_idx),
                    "inventory": add_result.get("data", {})
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in shop_buy: {e}")
            return {"success": False, "message": str(e)}
