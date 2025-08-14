

from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from game_class import GameDataManager, ResourceManager

import time
from datetime import datetime, timedelta

'''
아이템 관련 API 코드:
4001: 아이템 정보 조회
4002: 아이템 생성/획득
4003: 아이템 사용
4004: 아이템 삭제
4005: 사용자 아이템 목록 조회
'''

class ItemManager():
    CONFIG_TYPE = 'items'
    
    def __init__(self, api_code: int, data: dict, db: Session):
        self.api_code = api_code
        self.data = data
        self.db = db
        
        return
    
    def _validate_input(self):
        """공통 입력값 검증"""
        user_no = self.data.get('user_no')
        
        if not user_no:
            return {
                "success": False, 
                "message": f"Missing required field: user_no: {user_no}", 
                "data": {}
            }
        return None
    
    def _validate_item_input(self):
        """아이템 관련 입력값 검증"""
        user_no = self.data.get('user_no')
        item_idx = self.data.get('item_idx')
        
        if not user_no or not item_idx:
            return {
                "success": False, 
                "message": f"Missing required fields: user_no: {user_no} or item_idx: {item_idx}", 
                "data": {}
            }
        return None
    
    def _format_item_data(self, item):
        """아이템 데이터를 응답 형태로 포맷팅"""
        return {
            "id": item.id,
            "user_no": item.user_no,
            "item_idx": item.item_idx,
            "quantity": item.quantity,
            "created_dt": item.created_dt.isoformat() if item.created_dt else None,
            "last_dt": item.last_dt.isoformat() if item.last_dt else None
        }
    
    def _get_user_item(self, user_no, item_idx):
        """사용자의 특정 아이템 조회"""
        return self.db.query(models.UserItem).filter(
            models.UserItem.user_no == user_no,
            models.UserItem.item_idx == item_idx
        ).first()
    
    def _get_user_items(self, user_no):
        """사용자의 모든 아이템 목록 조회"""
        return self.db.query(models.UserItem).filter(
            models.UserItem.user_no == user_no,
            models.UserItem.quantity > 0
        ).all()
    
    def _check_item_config(self, item_idx):
        """아이템 설정 정보 확인"""
        try:
            item_config = GameDataManager.require_configs[self.CONFIG_TYPE].get(item_idx)
            if not item_config:
                return None, f"Item configuration not found for item_idx: {item_idx}"
            return item_config, None
        except Exception as e:
            return None, f"Error accessing item configuration: {str(e)}"
    
    def item_info(self):
        """
           api_code: 4001
           info: 사용자의 특정 아이템 정보를 조회합니다.
        """
        try:
            # 입력값 검증
            validation_error = self._validate_item_input()
            if validation_error:
                return validation_error
            
            user_no = self.data.get('user_no')
            item_idx = self.data.get('item_idx')
            
            # 아이템 조회
            user_item = self._get_user_item(user_no, item_idx)
            
            if not user_item:
                return {
                    "success": False, 
                    "message": f"Item not found: user_no:{user_no} and item_idx: {item_idx}", 
                    "data": {}
                }
            
            return {
                "success": True,
                "message": "Item info retrieved successfully",
                "data": self._format_item_data(user_item)
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving item info: {str(e)}", "data": {}}
    
    def item_create(self):
        """
           api_code: 4002
           info: 사용자에게 아이템을 생성/지급합니다.
        """
        try:
            # 입력값 검증
            validation_error = self._validate_item_input()
            if validation_error:
                return validation_error
            
            user_no = self.data.get('user_no')
            item_idx = self.data.get('item_idx')
            quantity = self.data.get('quantity', 1)  # 기본값 1개
            
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            # 아이템 설정 확인
            item_config, error_msg = self._check_item_config(item_idx)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            current_time = datetime.utcnow()
            
            # 기존 아이템 조회
            user_item = self._get_user_item(user_no, item_idx)
            
            if user_item:
                # 기존 아이템이 있으면 수량 증가
                user_item.quantity += quantity
                user_item.last_dt = current_time
                message = f"Added {quantity} {item_config.get('name', 'items')}. Total: {user_item.quantity}"
            else:
                # 새 아이템 생성
                user_item = models.UserItem(
                    user_no=user_no,
                    item_idx=item_idx,
                    quantity=quantity,
                    created_dt=current_time,
                    last_dt=current_time
                )
                self.db.add(user_item)
                message = f"Created {quantity} {item_config.get('name', 'items')}"
            
            self.db.commit()
            self.db.refresh(user_item)
            
            return {
                "success": True,
                "message": message,
                "data": self._format_item_data(user_item)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error creating item: {str(e)}", "data": {}}
    
    def item_use(self):
        """
           api_code: 4003
           info: 아이템을 사용합니다.
        """
        try:
            # 입력값 검증
            validation_error = self._validate_item_input()
            if validation_error:
                return validation_error
            
            user_no = self.data.get('user_no')
            item_idx = self.data.get('item_idx')
            quantity = self.data.get('quantity', 1)  # 기본값 1개
            
            if quantity <= 0:
                return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
            
            # 아이템 설정 확인
            item_config, error_msg = self._check_item_config(item_idx)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 사용자 아이템 조회
            user_item = self._get_user_item(user_no, item_idx)
            if not user_item:
                return {"success": False, "message": "Item not found", "data": {}}
            
            # 수량 확인
            if user_item.quantity < quantity:
                return {
                    "success": False, 
                    "message": f"Not enough items. Have: {user_item.quantity}, Need: {quantity}", 
                    "data": {}
                }
            
            # 아이템 효과 적용
            effect_result = self._apply_item_effect(user_no, item_config, quantity)
            if not effect_result["success"]:
                return effect_result
            
            # 아이템 수량 감소
            user_item.quantity -= quantity
            user_item.last_dt = datetime.utcnow()
            
            # 수량이 0이 되면 아이템 삭제
            if user_item.quantity <= 0:
                self.db.delete(user_item)
                message = f"Used all {item_config.get('name', 'items')}. Item removed from inventory."
                data = {}
            else:
                message = f"Used {quantity} {item_config.get('name', 'items')}. Remaining: {user_item.quantity}"
                data = self._format_item_data(user_item)
            
            self.db.commit()
            if user_item.quantity > 0:
                self.db.refresh(user_item)
            
            return {
                "success": True,
                "message": message + f" Effect: {effect_result['message']}",
                "data": data
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error using item: {str(e)}", "data": {}}
    
    def _apply_item_effect(self, user_no, item_config, quantity):
        """아이템 효과 적용"""
        try:
            effect = item_config.get('effect', {})
            effect_type = effect.get('type')
            
            if effect_type == 'resource':
                # 자원 지급 효과
                resources = effect.get('resources', {})
                resource_manager = ResourceManager(self.db)
                
                # 수량만큼 곱해서 자원 지급
                for resource_type, amount in resources.items():
                    total_amount = amount * quantity
                    resource_manager.add_resource(user_no, resource_type, total_amount)
                
                return {
                    "success": True,
                    "message": f"Added resources: {resources}"
                }
            
            elif effect_type == 'buff':
                # 버프 효과 (추후 구현)
                return {
                    "success": True,
                    "message": f"Applied buff effect"
                }
            
            elif effect_type == 'instant':
                # 즉시 효과 (추후 구현)
                return {
                    "success": True,
                    "message": f"Applied instant effect"
                }
            
            else:
                return {
                    "success": False,
                    "message": f"Unknown item effect type: {effect_type}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Error applying item effect: {str(e)}"
            }
    
    def item_delete(self):
        """
           api_code: 4004
           info: 아이템을 삭제합니다.
        """
        try:
            # 입력값 검증
            validation_error = self._validate_item_input()
            if validation_error:
                return validation_error
            
            user_no = self.data.get('user_no')
            item_idx = self.data.get('item_idx')
            quantity = self.data.get('quantity', None)  # None이면 전체 삭제
            
            # 사용자 아이템 조회
            user_item = self._get_user_item(user_no, item_idx)
            if not user_item:
                return {"success": False, "message": "Item not found", "data": {}}
            
            if quantity is None or quantity >= user_item.quantity:
                # 전체 삭제
                deleted_quantity = user_item.quantity
                self.db.delete(user_item)
                message = f"Deleted all {deleted_quantity} items"
                data = {}
            else:
                # 부분 삭제
                if quantity <= 0:
                    return {"success": False, "message": "Quantity must be greater than 0", "data": {}}
                
                user_item.quantity -= quantity
                user_item.last_dt = datetime.utcnow()
                message = f"Deleted {quantity} items. Remaining: {user_item.quantity}"
                data = self._format_item_data(user_item)
            
            self.db.commit()
            if quantity is None or quantity >= user_item.quantity:
                pass  # 이미 삭제됨
            else:
                self.db.refresh(user_item)
            
            return {
                "success": True,
                "message": message,
                "data": data
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error deleting item: {str(e)}", "data": {}}
    
    def item_list(self):
        """
           api_code: 4005
           info: 사용자의 모든 아이템 목록을 조회합니다.
        """
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            user_no = self.data.get('user_no')
            
            # 사용자 아이템 목록 조회
            user_items = self._get_user_items(user_no)
            
            items_data = [self._format_item_data(item) for item in user_items]
            
            return {
                "success": True,
                "message": f"Retrieved {len(items_data)} items",
                "data": {
                    "items": items_data,
                    "total_count": len(items_data)
                }
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving item list: {str(e)}", "data": {}}
    
    def active(self):
        """API 요청을 적절한 메서드로 라우팅합니다."""
        
        # 공통 입력값 검증은 각 메서드에서 수행
        api_code = self.api_code
        
        if api_code == 4001:
            return self.item_info()
        
        elif api_code == 4002:
            return self.item_create()
        
        elif api_code == 4003: 
            return self.item_use()
        
        elif api_code == 4004: 
            return self.item_delete()
        
        elif api_code == 4005:
            return self.item_list()
        
        else:
            return {
                "success": False, 
                "message": f"Unknown API code: {api_code}", 
                "data": {}
            }