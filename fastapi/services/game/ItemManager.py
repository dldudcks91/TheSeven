from sqlalchemy.orm import Session
import models
from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime
import logging


class ItemManager:
    """아이템 관리자 - 컴포넌트 기반 구조"""
    
    CONFIG_TYPE = 'item'
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None 
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_items = None
        self.logger = logging.getLogger(self.__class__.__name__)
        
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_items = None

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
        
    def _validate_input(self):
        """공통 입력값 검증"""
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }

        item_idx = self.data.get('item_idx')
        if not item_idx:
            return {
                "success": False,  
                "message": f"Missing required fields: item_idx",  
                "data": {}
            }
        return None
    
    def _format_item_for_cache(self, item_data):
        """캐시용 아이템 데이터 포맷팅"""
        try:
            if isinstance(item_data, dict):
                return {
                    "user_no": item_data.get('user_no'),
                    "item_idx": item_data.get('item_idx'),
                    "quantity": item_data.get('quantity', 0),
                    "cached_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "user_no": item_data.user_no,
                    "item_idx": item_data.item_idx,
                    "quantity": item_data.quantity,
                    "cached_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            self.logger.error(f"Error formatting item data for cache: {e}")
            return {}
    
    async def get_user_items(self):
        """사용자 아이템 데이터를 캐시 우선으로 조회"""
        if self._cached_items is not None:
            return self._cached_items
        
        user_no = self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            item_redis = self.redis_manager.get_item_manager()
            self._cached_items = await item_redis.get_cached_items(user_no)
            
            if self._cached_items:
                self.logger.debug(f"Cache hit: Retrieved {len(self._cached_items)} items for user {user_no}")
                return self._cached_items
            
            # 2. 캐시 미스: DB에서 조회
            items_data = self.get_db_items(user_no)
            
            if items_data['success'] and items_data['data']:
                # 3. Redis에 캐싱
                cache_success = await item_redis.cache_user_items_data(user_no, items_data['data'])
                if cache_success:
                    self.logger.debug(f"Successfully cached {len(items_data['data'])} items for user {user_no}")
                
                self._cached_items = items_data['data']
            else:
                self._cached_items = {}
                
        except Exception as e:
            self.logger.error(f"Error getting user items for user {user_no}: {e}")
            self._cached_items = {}
        
        return self._cached_items
    
    def get_db_items(self, user_no):
        """DB에서 아이템 데이터만 순수하게 조회"""
        try:
            item_db = self.db_manager.get_item_manager()
            items_result = item_db.get_user_items(user_no)
            
            if not items_result['success']:
                return items_result
            
            # 데이터 포맷팅
            formatted_items = {}
            for item in items_result['data']:
                item_idx = item['item_idx']
                formatted_items[str(item_idx)] = self._format_item_for_cache(item)
            
            return {
                "success": True,
                "message": f"Loaded {len(formatted_items)} items from database",
                "data": formatted_items
            }
            
        except Exception as e:
            self.logger.error(f"Error loading items from DB for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    async def invalidate_user_item_cache(self, user_no: int):
        """사용자 아이템 캐시 무효화"""
        try:
            item_redis = self.redis_manager.get_item_manager()
            cache_invalidated = await item_redis.invalidate_item_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_items = None
            
            self.logger.debug(f"Item cache invalidated for user {user_no}: {cache_invalidated}")
            return cache_invalidated
            
        except Exception as e:
            self.logger.error(f"Error invalidating item cache for user {user_no}: {e}")
            return False
    
    #-------------------- 여기서부터 API 관련 로직 ---------------------------------------#
    
    async def item_info(self):
        """아이템 정보 조회 - 순수하게 데이터만 반환"""
        try:
            items_data = await self.get_user_items()
            
            return {
                "success": True,
                "message": f"Retrieved {len(items_data)} items",
                "data": items_data
            }
            
        except Exception as e:
            self.logger.error(f"Error getting item info: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def add_item(self):
        """아이템 추가"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            item_idx = self.data.get('item_idx')
            quantity = self.data.get('quantity', 1)
            
            if quantity <= 0:
                return {
                    "success": False,
                    "message": "Quantity must be greater than 0",
                    "data": {}
                }
            
            # 현재 보유량 조회
            items_data = await self.get_user_items()
            current_quantity = items_data.get(str(item_idx), {}).get('quantity', 0)
            new_quantity = current_quantity + quantity
            
            # DB 업데이트
            item_db = self.db_manager.get_item_manager()
            update_result = item_db.upsert_item(user_no, item_idx, new_quantity)
            
            if not update_result['success']:
                return update_result
            
            # Redis 캐시 업데이트
            item_redis = self.redis_manager.get_item_manager()
            item_data = self._format_item_for_cache({
                'user_no': user_no,
                'item_idx': item_idx,
                'quantity': new_quantity
            })
            await item_redis.update_cached_item(user_no, item_idx, item_data)
            
            # 메모리 캐시 무효화
            self._cached_items = None
            
            self.logger.info(f"Item added: user_no={user_no}, item_idx={item_idx}, quantity={quantity}, new_total={new_quantity}")
            
            return {
                "success": True,
                "message": "Item added successfully",
                "data": {
                    "item_idx": item_idx,
                    "added_quantity": quantity,
                    "new_quantity": new_quantity
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error adding item: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def use_item(self):
        """아이템 사용 (차감)"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            item_idx = self.data.get('item_idx')
            quantity = self.data.get('quantity', 1)
            
            if quantity <= 0:
                return {
                    "success": False,
                    "message": "Quantity must be greater than 0",
                    "data": {}
                }
            
            # 현재 보유량 조회
            items_data = await self.get_user_items()
            current_quantity = items_data.get(str(item_idx), {}).get('quantity', 0)
            
            if current_quantity < quantity:
                return {
                    "success": False,
                    "message": "Not enough items",
                    "data": {
                        "required": quantity,
                        "available": current_quantity
                    }
                }
            
            new_quantity = current_quantity - quantity
            
            # DB 업데이트
            item_db = self.db_manager.get_item_manager()
            update_result = item_db.update_item_quantity(user_no, item_idx, new_quantity)
            
            if not update_result['success']:
                return update_result
            
            # Redis 캐시 업데이트
            item_redis = self.redis_manager.get_item_manager()
            await item_redis.update_item_quantity(user_no, item_idx, new_quantity)
            
            # 메모리 캐시 무효화
            self._cached_items = None
            
            # 아이템 효과 적용
            effect_result = await self._apply_item_effect(item_idx, quantity)
            
            self.logger.info(f"Item used: user_no={user_no}, item_idx={item_idx}, quantity={quantity}, remaining={new_quantity}")
            
            return {
                "success": True,
                "message": "Item used successfully",
                "data": {
                    "item_idx": item_idx,
                    "used_quantity": quantity,
                    "remaining_quantity": new_quantity,
                    "effect_applied": effect_result.get('success', False)
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error using item: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def _apply_item_effect(self, item_idx: int, quantity: int):
        """아이템 효과 적용"""
        try:
            user_no = self.user_no
            
            # GameDataManager에서 아이템 메타데이터 조회 (BuildingManager 방식)
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                self.logger.warning("Item configuration not found")
                return {"success": False, "message": "Item config not found"}
            
            item_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(item_idx)
            
            if not item_config:
                self.logger.warning(f"Item config not found: {item_idx}")
                return {"success": False, "message": "Item config not found"}
            
            category = item_config.get('category')
            item_type = item_config.get('item_type')
            target_type = item_config.get('target_type')
            value = item_config.get('value', 0)
            
            # 카테고리별 효과 적용
            if category == 'speedup':
                # 가속 아이템 - 추후 구현
                self.logger.info(f"Applied speedup: target={target_type}, seconds={value * quantity}")
                
            elif category == 'resource':
                # 자원 아이템 - ResourceManager 호출
                self.logger.info(f"Applied resource: type={target_type}, amount={value * quantity}")
                
            elif category == 'chest':
                # 상자 아이템 - 랜덤 보상
                self.logger.info(f"Opened chest: item_idx={item_idx}, count={quantity}")
            
            return {"success": True, "message": "Item effect applied"}
            
        except Exception as e:
            self.logger.error(f"Error applying item effect: {e}")
            return {"success": False, "message": str(e)}
    
    async def get_item_detail(self):
        """특정 아이템 상세 정보 조회 (메타데이터 + 보유량)"""
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            item_idx = self.data.get('item_idx')
            user_no = self.user_no
            
            # 1. GameDataManager에서 메타데이터 조회 (BuildingManager 방식)
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                return {
                    "success": False,
                    "message": "Item configuration not found",
                    "data": {}
                }
            
            item_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(item_idx)
            
            if not item_config:
                return {
                    "success": False,
                    "message": f"Item not found: {item_idx}",
                    "data": {}
                }
            
            # 2. 보유량 조회
            items_data = await self.get_user_items()
            quantity = items_data.get(str(item_idx), {}).get('quantity', 0)
            
            return {
                "success": True,
                "message": "Item detail retrieved",
                "data": {
                    **item_config,
                    "quantity": quantity
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting item detail: {e}")
            return {"success": False, "message": str(e), "data": {}}