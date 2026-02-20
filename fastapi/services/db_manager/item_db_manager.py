from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import models
from datetime import datetime
import logging


class ItemDBManager:
    """아이템 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_model_class(self):
        return models.Item
    
    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        """응답 형태 통일"""
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def _serialize_model(self, model_instance) -> Dict[str, Any]:
        """모델 인스턴스를 딕셔너리로 변환"""
        return {
            "user_no": model_instance.user_no,
            "item_idx": model_instance.item_idx,
            "quantity": model_instance.quantity,
        }
    
    def get_user_items(self, user_no: int) -> Dict[str, Any]:
        """사용자의 모든 아이템 조회"""
        try:
            items = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.quantity > 0
            ).all()
            
            return self._format_response(
                True,
                f"Retrieved {len(items)} items",
                [self._serialize_model(item) for item in items]
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user items: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting user items: {e}")
            return self._format_response(False, f"Error getting items: {str(e)}")
    
    def get_user_item(self, user_no: int, item_idx: int) -> Dict[str, Any]:
        """특정 아이템 조회 - user_no로 권한 확인"""
        try:
            item = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.item_idx == item_idx
            ).first()
            
            if not item:
                return self._format_response(False, "Item not found")
            
            return self._format_response(
                True,
                "Item retrieved successfully",
                self._serialize_model(item)
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting item: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting item: {e}")
            return self._format_response(False, f"Error getting item: {str(e)}")
    
    def upsert_item(self, user_no: int, item_idx: int, quantity: int) -> Dict[str, Any]:
        """아이템 추가/업데이트 - commit하지 않음"""
        try:
            existing = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.item_idx == item_idx
            ).first()
            
            if existing:
                # 업데이트
                existing.quantity = quantity
                item_data = self._serialize_model(existing)
            else:
                # 생성
                new_item = models.Item(
                    user_no=user_no,
                    item_idx=item_idx,
                    quantity=quantity
                )
                self.db.add(new_item)
                self.db.flush()  # commit 대신 flush
                item_data = self._serialize_model(new_item)
            
            return self._format_response(
                True,
                "Item upserted successfully",
                item_data
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error upserting item: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error upserting item: {e}")
            return self._format_response(False, f"Error upserting item: {str(e)}")
    
    def update_item_quantity(self, user_no: int, item_idx: int, quantity: int) -> Dict[str, Any]:
        """아이템 수량 업데이트 - user_no로 권한 확인"""
        try:
            item = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.item_idx == item_idx
            ).first()
            
            if not item:
                return self._format_response(False, "Item not found or no permission")
            
            item.quantity = quantity
            
            # 수량이 0 이하면 삭제
            if quantity <= 0:
                self.db.delete(item)
            
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Item quantity updated successfully",
                self._serialize_model(item) if quantity > 0 else {"user_no": user_no, "item_idx": item_idx, "quantity": 0}
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating item quantity: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error updating item quantity: {e}")
            return self._format_response(False, f"Error updating item quantity: {str(e)}")
    
    def delete_item(self, user_no: int, item_idx: int) -> Dict[str, Any]:
        """아이템 삭제 - user_no로 권한 확인"""
        try:
            item = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.item_idx == item_idx
            ).first()
            
            if not item:
                return self._format_response(False, "Item not found or no permission")
            
            self.db.delete(item)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Item deleted successfully",
                {"user_no": user_no, "item_idx": item_idx}
            )
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting item: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error deleting item: {e}")
            return self._format_response(False, f"Error deleting item: {str(e)}")
    
    def get_item_count(self, user_no: int) -> int:
        """사용자가 보유한 아이템 종류 수"""
        try:
            count = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.quantity > 0
            ).count()
            
            return count
        except Exception as e:
            self.logger.error(f"Error getting item count: {e}")
            return 0
        
    def bulk_upsert_item(self, user_no: int, item_idx: int, item_data: Dict[str, Any]) -> Dict[str, Any]:

        
        try:
            existing = self.db.query(models.Item).filter(
                models.Item.user_no == user_no,
                models.Item.item_idx == item_idx
            ).first()
            
            if existing:
                existing.quantity = item_data.get('quantity', 0)
                existing.cached_at = item_data.get('cached_at')
            else:
                new_item = models.Item(
                    user_no=user_no,
                    item_idx=item_idx,
                    quantity=item_data.get('quantity', 0),
                    cached_at=item_data.get('cached_at')
                )
                self.db.add(new_item)
            
            self.db.flush()
            return self._format_response(True, "Item upserted successfully")
        except SQLAlchemyError as e:
            self.logger.error(f"Database error upserting item: {e}")
            return self._format_response(False, f"Database error: {str(e)}")