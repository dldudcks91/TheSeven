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
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold']
    
    def __init__(self, api_code: int, data: dict, db: Session):
        self.api_code = api_code
        self.data = data
        self.db = db
    
    def _get_resources(self, user_no):
        """자원 조회 헬퍼 메서드"""
        return self.db.query(models.Resources).filter(models.Resources.user_no == user_no).first()
    
    def check_require_resources(self, user_no, config_type, idx, lv):
        require_configs = GameDataManager.require_configs[config_type][idx][lv]
        now_resources = self._get_resources(user_no)
        now_food = now_resources.food
        require_food = require_configs['cost']['food']
        if now_food >= require_food:
            return True
        else:
            return False
    
    def consume_resources(self):
        
        
        return
        
    