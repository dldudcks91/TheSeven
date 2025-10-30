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
    
    async def get_user_resources(self, user_no: int):
        """사용자 자원 조회 - 객체 반환"""
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
        """자원 객체 저장 준비 - commit하지 않음 (트랜잭션용)"""
        try:
            # 음수 검증
            for resource_type in self.RESOURCE_TYPES:
                amount = getattr(resource_instance, resource_type, 0)
                if amount < 0:
                    return {
                        "success": False,
                        "message": f"Resource {resource_type} cannot be negative: {amount}",
                        "data": {}
                    }
            
            # 세션에 변경사항 반영 (commit하지 않음)
            self.db.flush()
            
            resource_data = self._format_resources_data(resource_instance)
            
            self.logger.debug(f"Prepared resources for save (user {resource_instance.user_no})")
            
            return {
                "success": True,
                "message": "Resources prepared for save",
                "data": resource_data
            }
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error preparing resources for save: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.logger.error(f"Error preparing resources for save: {e}")
            return {
                "success": False,
                "message": f"Error preparing resources: {str(e)}",
                "data": {}
            }
    
    def save_resources_with_commit(self, resource_instance) -> Dict[str, Any]:
        """자원 저장 + commit (독립적인 트랜잭션용)"""
        try:
            # 음수 검증
            for resource_type in self.RESOURCE_TYPES:
                amount = getattr(resource_instance, resource_type, 0)
                if amount < 0:
                    self.db.rollback()
                    return {
                        "success": False,
                        "message": f"Resource {resource_type} cannot be negative: {amount}",
                        "data": {}
                    }
            
            self.db.commit()
            self.db.refresh(resource_instance)
            
            resource_data = self._format_resources_data(resource_instance)
            
            self.logger.debug(f"Saved resources with commit for user {resource_instance.user_no}")
            
            return {
                "success": True,
                "message": "Resources saved successfully",
                "data": resource_data
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error saving resources: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error saving resources: {e}")
            return {
                "success": False,
                "message": f"Error saving resources: {str(e)}",
                "data": {}
            }
    
    def create_default_resources(self, user_no: int, initial_amounts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """기본 자원으로 사용자 자원 생성 - commit 포함"""
        try:
            default_amounts = {
                'food': 1000,
                'wood': 1000,
                'stone': 500,
                'gold': 500,
                'ruby': 0
            }
            
            if initial_amounts:
                default_amounts.update(initial_amounts)
            
            new_resources = models.Resources(
                user_no=user_no,
                food=default_amounts['food'],
                wood=default_amounts['wood'],
                stone=default_amounts['stone'],
                gold=default_amounts['gold'],
                ruby=default_amounts['ruby'],
            )
            
            self.db.add(new_resources)
            self.db.commit()
            self.db.refresh(new_resources)
            
            resource_data = self._format_resources_data(new_resources)
            
            self.logger.info(f"Created default resources for user {user_no}")
            
            return {
                "success": True,
                "message": "Default resources created successfully",
                "data": resource_data
            }
            
        except IntegrityError as e:
            self.db.rollback()
            self.logger.error(f"Integrity error creating resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": "User resources already exist or constraint violation",
                "data": {}
            }
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error creating resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error creating resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error creating resources: {str(e)}",
                "data": {}
            }
    
    def _format_resources_data(self, resources) -> Dict[str, Any]:
        """자원 데이터를 응답 형태로 포맷팅"""
        return {
            "id": resources.id,
            "user_no": resources.user_no,
            "food": resources.food,
            "wood": resources.wood,
            "stone": resources.stone,
            "gold": resources.gold,
            "ruby": resources.ruby,
        }