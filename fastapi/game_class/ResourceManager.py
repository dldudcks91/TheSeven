from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from game_class import GameDataManager


import time
from datetime import datetime, timedelta

'''
status 값
0: 정상 (업그레이드 가능)
1: 건설중  
2: 업그레이드중
'''
class ResourceManager:
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    #API 코드 상수 정의
    API_RESOURCE_INFO = 5001
    def __init__(self, db: Session):
        self.db = db
        self.now_resources = None
        
    def _get_resources(self, user_no):
        """자원 조회 헬퍼 메서드"""
        return self.db.query(models.Resources).filter(models.Resources.user_no == user_no).first()
    
    def _format_resources_data(self, resource):
        """건물 데이터를 응답 형태로 포맷팅"""
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
        """
            api_code: 5001
            info: 자원 정보를 조회합니다.
        """
        try:
            # 입력값 검증
            
            # 건물 조회
            user_resources = self._get_resources(user_no)
            
            # 건물 데이터 구성
            resources_data = {}
            
            # 기존 건물들 추가
            resource_data = self._format_resources_data(user_resources)
        
            return {
                "success": True,
                "message": f"Retrieved {len(resource_data)} resource info",
                "data": resource_data
                
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving buildings info: {str(e)}", "data": {}}
    def check_require_resources(self, user_no, costs):
        
        self.now_resources = self._get_resources(user_no)
        
        if not self.now_resources:
            return False # 유저의 자원 정보가 없으면 False
        for resource_type in self.RESOURCE_TYPES:
            now_amount = getattr(self.now_resources, resource_type, 0)
            if now_amount < costs.get(resource_type,0):
                return False
        return True
        
    
    def consume_resources(self, user_no, costs):
        for resource_type in self.RESOURCE_TYPES:
            now_amount = getattr(self.now_resources, resource_type, 0)
            
            setattr(self.now_resources, resource_type, now_amount - costs.get(resource_type,0))

        return
        
    def produce_resources(self, user_no, costs):
        
        for resource_type in self.RESOURCE_TYPES:
            now_amount = getattr(self.now_resources, resource_type, 0)
            
            setattr(self.now_resources, resource_type, now_amount + costs.get(resource_type,0))

        return
    
    