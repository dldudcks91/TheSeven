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
    
    def __init__(self, db: Session):
        self.db = db
        self.now_resources = None
        
    def _get_resources(self, user_no):
        """자원 조회 헬퍼 메서드"""
        return self.db.query(models.Resources).filter(models.Resources.user_no == user_no).first()
    
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
        
    