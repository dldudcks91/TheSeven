from sqlalchemy.orm import Session
import models
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime
import logging


class UserInitManager:
    """신규 유저 초기화 Manager"""
    
    # 초기 설정값
    INITIAL_CONFIG = {
        "resources": {
            "food": 2000,
            "wood": 2000,
            "stone": 2000,
            "gold": 2000,
            "ruby": 0
        },
        "buildings": [
            {"building_idx": 201, "building_lv": 1, "status": 0}  # 완성된 건물
        ]
    }
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def create_new_user(self):
        """
        신규 유저 초기화 (account_no 자동 생성)
        
        Returns:
            {
                "success": bool,
                "message": str,
                "data": {"user_no": int, "account_no": int}
            }
        """
        try:
            # UserInitDBManager 가져오기
            user_init_db = self.db_manager.get_user_init_manager()
            
            # 1. account_no 자동 생성
            account_result = user_init_db.generate_account_no()
            if not account_result['success']:
                return account_result
            
            account_no = account_result['data']['account_no']
            
            # 2. stat_nation 생성
            stat_result = user_init_db.create_stat_nation(account_no)
            if not stat_result['success']:
                return stat_result
            
            user_no = stat_result['data']['user_no']
            
            # 3. 초기 자원 생성
            resources_result = user_init_db.create_resources(
                user_no, 
                self.INITIAL_CONFIG["resources"]
            )
            if not resources_result['success']:
                self.logger.error(f"Failed to create resources: {resources_result['message']}")
                # 롤백은 외부에서 처리됨
                return resources_result
            
            # 4. 초기 건물 생성
            for building_config in self.INITIAL_CONFIG["buildings"]:
                building_result = user_init_db.create_building(user_no, building_config)
                if not building_result['success']:
                    self.logger.error(f"Failed to create building: {building_result['message']}")
                    return building_result
            
            # 5. DB Commit
            self.db_manager.commit()
            
            self.logger.info(f"New user created: account_no={account_no}, user_no={user_no}")
            
            return {
                "success": True,
                "message": "User created successfully",
                "data": {
                    "user_no": user_no,
                    "account_no": account_no
                }
            }
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error creating new user: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {}
            }
    
    async def check_user_exists(self, account_no: int) -> bool:
        """계정번호로 유저 존재 여부 확인"""
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.check_user_exists(account_no)
            
            if result['success']:
                return result['data'].get('exists', False)
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking user existence: {e}")
            return False
    
    async def get_user_no_by_account(self, account_no: int) -> int:
        """계정번호로 user_no 조회"""
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.get_user_by_account_no(account_no)
            
            if result['success']:
                return result['data'].get('user_no')
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting user_no: {e}")
            return None