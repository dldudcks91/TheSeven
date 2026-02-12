from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import models
from datetime import datetime
from typing import Dict, Any, Optional
import logging


class ResourceDBManager:
    """자원 데이터베이스 관리자 - 순수 DB 조작만 담당"""
    
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)
    
    # ============================================
    # 동기화용 bulk upsert
    # ============================================
    
    def bulk_upsert_resources(self, user_no: int, resources_data: Dict[str, str]) -> Dict[str, Any]:
        """
        Redis 자원 데이터를 MySQL에 upsert
        
        Args:
            user_no: 유저 번호
            resources_data: {'food': '99325150', 'wood': '100000', ...}
        """
        try:
            existing = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            
            if existing:
                for resource_type in self.RESOURCE_TYPES:
                    if resource_type in resources_data:
                        value = int(resources_data[resource_type])
                        if value < 0:
                            self.logger.warning(f"Negative resource {resource_type}={value} for user {user_no}, skipping")
                            continue
                        setattr(existing, resource_type, value)
            else:
                new_resources = models.Resources(
                    user_no=user_no,
                    food=int(resources_data.get('food', 0)),
                    wood=int(resources_data.get('wood', 0)),
                    stone=int(resources_data.get('stone', 0)),
                    gold=int(resources_data.get('gold', 0)),
                    ruby=int(resources_data.get('ruby', 0))
                )
                self.db.add(new_resources)
            
            self.db.flush()
            
            return {
                "success": True,
                "message": f"Synced resources for user {user_no}",
                "data": {}
            }
            
        except SQLAlchemyError as e:
            self.logger.error(f"bulk_upsert_resources error: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    # ============================================
    # 기존 메서드들 (변경 없음)
    # ============================================
    
    async def get_user_resources(self, user_no: int):
        try:
            resources = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            return resources
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting resources for user {user_no}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting resources for user {user_no}: {e}")
            return None
    
    def save_resources(self, resource_instance) -> Dict[str, Any]:
        try:
            for resource_type in self.RESOURCE_TYPES:
                amount = getattr(resource_instance, resource_type, 0)
                if amount < 0:
                    return {
                        "success": False,
                        "message": f"Resource {resource_type} cannot be negative: {amount}",
                        "data": {}
                    }
            self.db.flush()
            resource_data = self._format_resources_data(resource_instance)
            return {"success": True, "message": "Resources prepared for save", "data": resource_data}
        except SQLAlchemyError as e:
            self.logger.error(f"Database error preparing resources for save: {e}")
            return {"success": False, "message": f"Database error: {str(e)}", "data": {}}
    
    def save_resources_with_commit(self, resource_instance) -> Dict[str, Any]:
        try:
            for resource_type in self.RESOURCE_TYPES:
                amount = getattr(resource_instance, resource_type, 0)
                if amount < 0:
                    self.db.rollback()
                    return {"success": False, "message": f"Resource {resource_type} cannot be negative: {amount}", "data": {}}
            self.db.commit()
            self.db.refresh(resource_instance)
            resource_data = self._format_resources_data(resource_instance)
            return {"success": True, "message": "Resources saved successfully", "data": resource_data}
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error saving resources: {e}")
            return {"success": False, "message": f"Database error: {str(e)}", "data": {}}
    
    def create_default_resources(self, user_no: int, initial_amounts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        try:
            default_amounts = {'food': 1000, 'wood': 1000, 'stone': 500, 'gold': 500, 'ruby': 0}
            if initial_amounts:
                default_amounts.update(initial_amounts)
            new_resources = models.Resources(user_no=user_no, **default_amounts)
            self.db.add(new_resources)
            self.db.commit()
            self.db.refresh(new_resources)
            resource_data = self._format_resources_data(new_resources)
            return {"success": True, "message": "Default resources created successfully", "data": resource_data}
        except IntegrityError as e:
            self.db.rollback()
            return {"success": False, "message": "User resources already exist or constraint violation", "data": {}}
        except SQLAlchemyError as e:
            self.db.rollback()
            return {"success": False, "message": f"Database error: {str(e)}", "data": {}}
    
    def _format_resources_data(self, resources) -> Dict[str, Any]:
        return {
            "id": resources.id,
            "user_no": resources.user_no,
            "food": resources.food,
            "wood": resources.wood,
            "stone": resources.stone,
            "gold": resources.gold,
            "ruby": resources.ruby,
        }
