from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from services.system import GameDataManager
from services.db_manager import DBManager, ResourceDBManager
import time
from datetime import datetime, timedelta
import logging


class ResourceManager:
    """자원 관리자 - 비즈니스 로직 담당"""
    
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    # API 코드 상수 정의
    API_RESOURCE_INFO = 1011
    
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager
        self.now_resources = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.resource_db = self.db_manager.get_resource_manager()
        
    def _get_resources(self, user_no):
        """자원 조회 헬퍼 메서드"""
        return self.resource_db.get_user_resources(user_no)
    
    def _format_resources_data(self, resource):
        """자원 데이터를 응답 형태로 포맷팅"""
        return {
            "id": resource.id,
            "user_no": resource.user_no,
            "food": resource.food,
            "wood": resource.wood,
            "stone": resource.stone,
            "gold": resource.gold,
            "ruby": resource.ruby,
        }
    
    def resource_info(self, user_no):
        """자원 정보를 조회합니다"""
        try:
            user_resources = self._get_resources(user_no)
            
            if not user_resources:
                return {
                    "success": False,
                    "message": "User resources not found",
                    "data": {}
                }
            
            resource_data = self._format_resources_data(user_resources)
        
            return {
                "success": True,
                "message": "Retrieved resource info successfully",
                "data": resource_data
            }
            
        except Exception as e:
            self.logger.error(f"Error retrieving resource info for user {user_no}: {e}")
            return {
                "success": False, 
                "message": f"Error retrieving resource info: {str(e)}", 
                "data": {}
            }
    
    def check_require_resources(self, user_no, costs):
        """필요한 자원이 충분한지 확인하고 self.now_resources에 저장"""
        try:
            self.now_resources = self._get_resources(user_no)
            
            if not self.now_resources:
                self.logger.warning(f"No resources found for user {user_no}")
                return False
            
            # 자원 충분성 검사
            for resource_type in self.RESOURCE_TYPES:
                now_amount = getattr(self.now_resources, resource_type, 0)
                required_amount = costs.get(resource_type, 0)
                
                if now_amount < required_amount:
                    self.logger.debug(f"Insufficient {resource_type} for user {user_no}: need {required_amount}, have {now_amount}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking resources for user {user_no}: {e}")
            return False
    
    def consume_resources(self, user_no, costs):
        """자원 소모 - check_require_resources가 먼저 호출되어야 함"""
        try:
            # 자원이 로드되지 않았다면 체크부터 실행
            if not self.now_resources:
                if not self.check_require_resources(user_no, costs):
                    return False
            
            # 메모리에서 자원 차감
            for resource_type in self.RESOURCE_TYPES:
                cost = costs.get(resource_type, 0)
                if cost > 0:  # 0보다 큰 경우만 처리
                    current_amount = getattr(self.now_resources, resource_type, 0)
                    new_amount = current_amount - cost
                    setattr(self.now_resources, resource_type, new_amount)
                    
                    self.logger.debug(f"Consumed {cost} {resource_type} for user {user_no}: {current_amount} -> {new_amount}")
            
            # DB에 저장 (ResourceDBManager의 save_resources 사용)
            save_result = self.resource_db.save_resources(self.now_resources)
            
            if not save_result['success']:
                self.logger.error(f"Failed to save resources: {save_result['message']}")
                return False
                
            self.logger.info(f"Successfully consumed resources for user {user_no}: {costs}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error consuming resources for user {user_no}: {e}")
            return False
    
    def produce_resources(self, user_no, gains):
        """자원 생산 - 기존 자원에 추가"""
        try:
            # 자원 정보가 없으면 새로 로드
            if not self.now_resources:
                self.now_resources = self._get_resources(user_no)
                if not self.now_resources:
                    self.logger.error(f"No resources found for user {user_no}")
                    return False
            
            # 메모리에서 자원 증가
            for resource_type in self.RESOURCE_TYPES:
                gain = gains.get(resource_type, 0)
                if gain > 0:  # 0보다 큰 경우만 처리
                    current_amount = getattr(self.now_resources, resource_type, 0)
                    new_amount = current_amount + gain
                    setattr(self.now_resources, resource_type, new_amount)
                    
                    self.logger.debug(f"Produced {gain} {resource_type} for user {user_no}: {current_amount} -> {new_amount}")
            
            # DB에 저장
            save_result = self.resource_db.save_resources(self.now_resources)
            
            if not save_result['success']:
                self.logger.error(f"Failed to save resources: {save_result['message']}")
                return False
                
            self.logger.info(f"Successfully produced resources for user {user_no}: {gains}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error producing resources for user {user_no}: {e}")
            return False
    
    def get_current_resources(self):
        """현재 로드된 자원 정보 반환"""
        if not self.now_resources:
            return None
        return self._format_resources_data(self.now_resources)
    
    def clear_cache(self):
        """캐시된 자원 정보 초기화"""
        self.now_resources = None
    
    def validate_resource_amounts(self, resources_dict):
        """자원 양 검증 유틸리티"""
        for resource_type, amount in resources_dict.items():
            if resource_type not in self.RESOURCE_TYPES:
                return False, f"Invalid resource type: {resource_type}"
            
            if not isinstance(amount, (int, float)) or amount < 0:
                return False, f"Invalid amount for {resource_type}: {amount}"
        
        return True, "Valid"
    
    def get_resource_shortage(self, user_no, required_resources):
        """부족한 자원 목록 반환"""
        try:
            current_resources = self._get_resources(user_no)
            if not current_resources:
                return {"error": "User resources not found"}
            
            shortages = {}
            for resource_type, required_amount in required_resources.items():
                current_amount = getattr(current_resources, resource_type, 0)
                if current_amount < required_amount:
                    shortages[resource_type] = {
                        "required": required_amount,
                        "current": current_amount,
                        "shortage": required_amount - current_amount
                    }
            
            return shortages
            
        except Exception as e:
            self.logger.error(f"Error getting resource shortage for user {user_no}: {e}")
            return {"error": str(e)}