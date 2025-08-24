
from sqlalchemy.orm import Session
from sqlalchemy import or_

import models, schemas # 모델 및 스키마 파일 import
from services import GameDataManager
import time
from datetime import datetime, timedelta


'''
status 값
0: 비활성
1: 활성
2: 만료됨
'''

class BuffManager:
    
    
    #API 코드 상수 정의
    API_BUFF_INFO = 10012
    CONFIG_TYPE = 'buff'
    
    BUFF_TYPES = {
        1: 'construction',
        2: 'research',
        3: 'attack', 
        4: 'defense',
        5: 'movement',
        6: 'production'
        }
    
    def __init__(self, db: Session):
        self.db = db
        self.now_buffs = None
        self.buff_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]
        
    def _get_buffs(self, user_no, ally_no = 0):
        """버프 조회 헬퍼 메서드"""
        return self.db.query(models.Buff).filter(
            
            or_((models.Buff.buff_type == 0, models.Buff.target_no == 0),
                (models.Buff.buff_type == 1, models.Buff.target_no == ally_no)
                (models.Buff.buff_type == 2, models.Buff.target_no == user_no)
                
                )
            )
    
    
    def _format_buffs_data(self, buff):
        """버프 데이터를 응답 형태로 포맷팅"""
        return {
            "id": buff.id,
            "buff_type": buff.buff_type,
            "target_no": buff.target_no,
            "buff_idx": buff.buff_idx,
            "start_time": buff.start_time.isoformat() if buff.start_time else None,
            "end_time": buff.end_time.isoformat() if buff.end_time else None
        }
    
    
    
    
    
    
    def buff_info(self, user_no):
        """
            api_code: 1012
            info: 버프 정보를 조회합니다.
        """
        try:
            # 버프 조회
            user_buffs = self._get_buffs(user_no)
            
            # 버프 데이터 구성
            buff_data = self._format_buffs_data(user_buffs)
        
            return {
                "success": True,
                "message": f"Retrieved buff info",
                "data": buff_data
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving buff info: {str(e)}", "data": {}}
    
    def check_buff_by_user(self, user_no, buff_type):
        """특정 버프가 활성화되어 있는지 확인"""
        self.now_buffs = self._get_buffs(user_no)
        
        if not self.now_buffs:
            return False # 유저의 버프 정보가 없으면 False
            
        buff_status = getattr(self.now_buffs, buff_type, 0)
        return buff_status == 1  # 1이면 활성
    
    
    def get_buff_value(self, user_no, buff_type):
        """특정 버프의 효과값을 반환"""
        if not self.check_buff_active(user_no, buff_type):
            return 0
            
        # 버프가 활성화되어 있으면 설정된 효과값 반환
        try:
            buff_config = GameDataManager.BUFF_CONFIGS.get(buff_type, {})
            return buff_config.get('value', 0)
        except:
            return 0
    
    def apply_buff(self, user_no, buff_type):
        """버프를 활성화"""
        self.now_buffs = self._get_buffs(user_no)
        
        if not self.now_buffs:
            return False
            
        if buff_type in self.BUFF_TYPES:
            setattr(self.now_buffs, buff_type, 1)
            self.now_buffs.last_dt = datetime.utcnow()
            return True
        return False
    
    def remove_buff(self, user_no, buff_type):
        """버프를 비활성화"""
        self.now_buffs = self._get_buffs(user_no)
        
        if not self.now_buffs:
            return False
            
        if buff_type in self.BUFF_TYPES:
            setattr(self.now_buffs, buff_type, 0)
            self.now_buffs.last_dt = datetime.utcnow()
            return True
        return False
    
    def get_all_active_buffs(self, user_no):
        """모든 활성 버프 목록 반환"""
        self.now_buffs = self._get_buffs(user_no)
        
        if not self.now_buffs:
            return []
            
        active_buffs = []
        for buff_type in self.BUFF_TYPES:
            if getattr(self.now_buffs, buff_type, 0) == 1:
                active_buffs.append(buff_type)
                
        return active_buffs
    
    def calculate_buffed_value(self, user_no, base_value, buff_type):
        """기본값에 버프 효과를 적용한 최종값 계산"""
        if not self.check_buff_active(user_no, buff_type):
            return base_value
            
        buff_value = self.get_buff_value(user_no, buff_type)
        
        # 버프 효과를 퍼센트로 적용 (예: 20% 증가)
        return int(base_value * (1 + buff_value / 100))