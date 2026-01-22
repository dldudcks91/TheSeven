from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime
import logging


class ItemManager:
    """아이템 관리자 - Redis 중심 구조 (DB 업데이트는 별도 Task 처리)"""
    
    CONFIG_TYPE = 'item'
    
    def __init__(self, db_manager:DBManager, redis_manager: RedisManager):
        self._user_no: int = None 
        self._data: dict = None
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
    
    async def get_user_items(self):
        """Redis에서 사용자 아이템 데이터 조회 (메모리 캐시 활용)"""
        if self._cached_items is not None:
            return self._cached_items
        
        user_no = self.user_no
        
        try:
            # Redis에서 조회
            item_redis = self.redis_manager.get_item_manager()
            self._cached_items = await item_redis.get_cached_items(user_no)
            
            if self._cached_items:
                self.logger.debug(f"Cache hit: Retrieved {len(self._cached_items)} items for user {user_no}")
            else:
                self.logger.warning(f"No items found in Redis for user {user_no}")
                self._cached_items = {}
                
        except Exception as e:
            self.logger.error(f"Error getting user items for user {user_no}: {e}")
            self._cached_items = {}
        
        return self._cached_items
    
    async def invalidate_user_item_cache(self, user_no: int):
        """사용자 아이템 메모리 캐시 무효화 (Redis는 유지)"""
        try:
            # 메모리 캐시만 무효화
            if self._user_no == user_no:
                self._cached_items = None
            
            self.logger.debug(f"Item memory cache invalidated for user {user_no}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error invalidating item cache for user {user_no}: {e}")
            return False
    
    #-------------------- 여기서부터 API 관련 로직 ---------------------------------------#
    
    async def item_info(self):
        """아이템 정보 조회 - Redis에서 데이터 반환"""
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
        """아이템 추가 - Redis만 업데이트"""
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
            
            # 현재 보유량 조회 (Redis)
            items_data = await self.get_user_items()
            current_quantity = items_data.get(str(item_idx), {}).get('quantity', 0)
            new_quantity = current_quantity + quantity
            
            # Redis 업데이트
            item_redis = self.redis_manager.get_item_manager()
            await item_redis.update_item_quantity(user_no, item_idx, new_quantity)
            
            
            
            self.logger.info(f"Item added (Redis): user_no={user_no}, item_idx={item_idx}, quantity={quantity}, new_total={new_quantity}")
            
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
        """아이템 사용 - Redis만 업데이트, 효과 적용 후 차감"""
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
            
            # 현재 보유량 조회 (Redis)
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
            
            # 1. 아이템 효과 적용 (실패하면 차감하지 않음)
            effect_result = await self._apply_item_effect(item_idx, quantity)
            if not effect_result.get('success'):
                return {
                    "success": False,
                    "message": f"Failed to apply item effect: {effect_result.get('message')}",
                    "data": {}
                }
            
            # 2. 효과 적용 성공 후 아이템 차감 (Redis)
            new_quantity = current_quantity - quantity
            
            item_redis = self.redis_manager.get_item_manager()
            await item_redis.update_item_quantity(user_no, item_idx, new_quantity)
            
            # 메모리 캐시 무효화
            self._cached_items = None
            
            self.logger.info(f"Item used (Redis): user_no={user_no}, item_idx={item_idx}, quantity={quantity}, remaining={new_quantity}")
            
            return {
                "success": True,
                "message": "Item used successfully",
                "data": {
                    "item_idx": item_idx,
                    "used_quantity": quantity,
                    "remaining_quantity": new_quantity,
                    "effect": effect_result.get('data', {})
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error using item: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def _apply_item_effect(self, item_idx: int, quantity: int):
        """아이템 효과 적용 - ResourceManager를 통해 Redis 업데이트"""
        try:
            user_no = self.user_no
            
            # GameDataManager에서 아이템 메타데이터 조회
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                self.logger.warning("Item configuration not found")
                return {"success": False, "message": "Item config not found"}
            
            item_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(item_idx)
            
            if not item_config:
                self.logger.warning(f"Item config not found: {item_idx}")
                return {"success": False, "message": f"Item {item_idx} config not found"}
            
            category = item_config.get('category')
            item_type = item_config.get('item_type')
            target_type = item_config.get('target_type')
            value = item_config.get('value', 0)
            
            effect_data = {}
            
            # 카테고리별 효과 적용
            if category == 'speedup':
                # 가속 아이템 - 추후 구현 (Building/Research 타이머 감소)
                total_seconds = value * quantity
                self.logger.info(f"Speedup effect: target={target_type}, seconds={total_seconds}")
                effect_data = {
                    "category": "speedup",
                    "target": target_type,
                    "seconds": total_seconds
                }
                
            elif category == 'resource':
                # 자원 아이템 - Redis ResourceManager 호출
                total_amount = value * quantity
                
                # ResourceManager를 통해 자원 추가 (Redis만 업데이트)
                resource_redis = self.redis_manager.get_resource_manager()
                
                if target_type in ['food', 'wood', 'stone', 'gold', 'ruby']:
                    await resource_redis.update_resource(user_no, target_type, total_amount)
                    self.logger.info(f"Applied resource: user={user_no}, type={target_type}, amount={+total_amount}")
                    effect_data = {
                        "category": "resource",
                        "resource_type": target_type,
                        "amount": total_amount
                    }
                else:
                    return {"success": False, "message": f"Unknown resource type: {target_type}"}
                
            elif category == 'chest':
                # 상자 아이템 - 랜덤 보상 (추후 구현)
                self.logger.info(f"Chest opened: item_idx={item_idx}, count={quantity}")
                effect_data = {
                    "category": "chest",
                    "item_idx": item_idx,
                    "count": quantity
                }
            
            else:
                return {"success": False, "message": f"Unknown item category: {category}"}
            
            return {
                "success": True,
                "message": "Item effect applied",
                "data": effect_data
            }
            
        except Exception as e:
            self.logger.error(f"Error applying item effect: {e}")
            return {"success": False, "message": str(e)}
    
    async def get_item_detail(self):
        """특정 아이템 상세 정보 조회 (메타데이터 + Redis 보유량)"""
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            item_idx = self.data.get('item_idx')
            user_no = self.user_no
            
            # 1. GameDataManager에서 메타데이터 조회
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
            
            # 2. Redis에서 보유량 조회
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