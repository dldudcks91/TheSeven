
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import models
from datetime import datetime
from typing import Dict, Any, Optional
import logging


class ResourceDBManager:
    """자원 데이터베이스 관리자"""
    
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_user_resources(self, user_no: int) -> Dict[str, Any]:
        """사용자 자원 조회"""
        try:
            resources = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            
            if not resources:
                # 사용자 자원이 없으면 기본값으로 생성
                return self.create_default_resources(user_no)
            
            resource_data = self._format_resources_data(resources)
            
            return {
                "success": True,
                "message": "User resources retrieved successfully",
                "data": resource_data
            }
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.logger.error(f"Error getting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error retrieving resources: {str(e)}",
                "data": {}
            }
    
    def create_default_resources(self, user_no: int, initial_amounts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """기본 자원으로 사용자 자원 생성"""
        try:
            # 기본값 설정
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
                last_dt=datetime.utcnow()
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
    
    def update_user_resources(self, user_no: int, changes: Dict[str, int]) -> Dict[str, Any]:
        """사용자 자원 업데이트 (증가/감소)"""
        try:
            resources = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            
            if not resources:
                return {
                    "success": False,
                    "message": "User resources not found",
                    "data": {}
                }
            
            # 변경사항 적용 전 검증
            for resource_type, change_amount in changes.items():
                if resource_type not in self.RESOURCE_TYPES:
                    return {
                        "success": False,
                        "message": f"Invalid resource type: {resource_type}",
                        "data": {}
                    }
                
                current_amount = getattr(resources, resource_type, 0)
                new_amount = current_amount + change_amount
                
                # 자원이 음수가 되는 것 방지
                if new_amount < 0:
                    return {
                        "success": False,
                        "message": f"Insufficient {resource_type}: need {abs(change_amount)}, have {current_amount}",
                        "data": {}
                    }
            
            # 검증 통과 후 실제 업데이트 적용
            for resource_type, change_amount in changes.items():
                current_amount = getattr(resources, resource_type, 0)
                new_amount = current_amount + change_amount
                setattr(resources, resource_type, new_amount)
            
            # 마지막 업데이트 시간 갱신
            resources.last_dt = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(resources)
            
            resource_data = self._format_resources_data(resources)
            
            self.logger.debug(f"Updated resources for user {user_no}: {changes}")
            
            return {
                "success": True,
                "message": "Resources updated successfully",
                "data": resource_data
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error updating resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error updating resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error updating resources: {str(e)}",
                "data": {}
            }
    
    def set_user_resources(self, user_no: int, amounts: Dict[str, int]) -> Dict[str, Any]:
        """사용자 자원을 특정 값으로 설정"""
        try:
            resources = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            
            if not resources:
                return {
                    "success": False,
                    "message": "User resources not found",
                    "data": {}
                }
            
            # 값 검증
            for resource_type, amount in amounts.items():
                if resource_type not in self.RESOURCE_TYPES:
                    return {
                        "success": False,
                        "message": f"Invalid resource type: {resource_type}",
                        "data": {}
                    }
                
                if amount < 0:
                    return {
                        "success": False,
                        "message": f"Resource amount cannot be negative: {resource_type}={amount}",
                        "data": {}
                    }
            
            # 자원 설정
            for resource_type, amount in amounts.items():
                setattr(resources, resource_type, amount)
            
            resources.last_dt = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(resources)
            
            resource_data = self._format_resources_data(resources)
            
            self.logger.debug(f"Set resources for user {user_no}: {amounts}")
            
            return {
                "success": True,
                "message": "Resources set successfully",
                "data": resource_data
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error setting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error setting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error setting resources: {str(e)}",
                "data": {}
            }
    
    def check_sufficient_resources(self, user_no: int, required: Dict[str, int]) -> Dict[str, Any]:
        """자원 보유량 충분한지 확인"""
        try:
            resources_result = self.get_user_resources(user_no)
            
            if not resources_result['success']:
                return resources_result
            
            resources = resources_result['data']
            insufficient = []
            
            for resource_type, required_amount in required.items():
                if resource_type not in self.RESOURCE_TYPES:
                    return {
                        "success": False,
                        "message": f"Invalid resource type: {resource_type}",
                        "data": {}
                    }
                
                current_amount = resources.get(resource_type, 0)
                if current_amount < required_amount:
                    insufficient.append({
                        "resource_type": resource_type,
                        "required": required_amount,
                        "current": current_amount,
                        "shortage": required_amount - current_amount
                    })
            
            if insufficient:
                return {
                    "success": False,
                    "message": "Insufficient resources",
                    "data": {
                        "sufficient": False,
                        "insufficient_resources": insufficient
                    }
                }
            
            return {
                "success": True,
                "message": "Resources are sufficient",
                "data": {
                    "sufficient": True,
                    "current_resources": resources
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error checking resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error checking resources: {str(e)}",
                "data": {}
            }
    
    def get_resource_history(self, user_no: int, limit: int = 50) -> Dict[str, Any]:
        """자원 변경 이력 조회 (별도 테이블이 있다면)"""
        # 이 기능은 resource_history 테이블이 있을 때 구현
        try:
            # 현재는 기본 구현만 제공
            return {
                "success": True,
                "message": "Resource history feature not implemented",
                "data": {
                    "history": [],
                    "note": "Resource history tracking requires separate table"
                }
            }
        except Exception as e:
            self.logger.error(f"Error getting resource history for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error getting resource history: {str(e)}",
                "data": {}
            }
    
    def reset_user_resources(self, user_no: int) -> Dict[str, Any]:
        """사용자 자원을 기본값으로 리셋"""
        try:
            resources = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            
            if not resources:
                return self.create_default_resources(user_no)
            
            # 기본값으로 리셋
            resources.food = 1000
            resources.wood = 1000
            resources.stone = 500
            resources.gold = 500
            resources.ruby = 0
            resources.last_dt = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(resources)
            
            resource_data = self._format_resources_data(resources)
            
            self.logger.info(f"Reset resources for user {user_no}")
            
            return {
                "success": True,
                "message": "Resources reset to default values",
                "data": resource_data
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error resetting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error resetting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error resetting resources: {str(e)}",
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
            "last_dt": resources.last_dt.isoformat() if resources.last_dt else None,
            "updated_at": datetime.utcnow().isoformat()
        }
    
    def delete_user_resources(self, user_no: int) -> Dict[str, Any]:
        """사용자 자원 삭제 (관리용)"""
        try:
            resources = self.db.query(models.Resources).filter(
                models.Resources.user_no == user_no
            ).first()
            
            if not resources:
                return {
                    "success": False,
                    "message": "User resources not found",
                    "data": {}
                }
            
            self.db.delete(resources)
            self.db.commit()
            
            self.logger.info(f"Deleted resources for user {user_no}")
            
            return {
                "success": True,
                "message": "User resources deleted successfully",
                "data": {"user_no": user_no}
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            self.logger.error(f"Database error deleting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error deleting resources for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error deleting resources: {str(e)}",
                "data": {}
            }