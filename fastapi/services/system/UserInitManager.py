from sqlalchemy.orm import Session
import models
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime
import logging
from typing import Dict, Any, Optional


class UserInitManager:
    """
    신규 유저 초기화 Manager - DB Lock 방식
    Redis 없이 DB만 사용하는 단순한 구조
    """
    
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
            {"building_idx": 201, "building_lv": 1, "status": 0}  # 본부
        ]
    }
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager = None):
        self.db_manager = db_manager
        self.redis_manager = redis_manager  # 나중에 필요하면 사용
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def create_new_user(self) -> Dict[str, Any]:
        """
        신규 유저 생성 - DB Lock 방식
        
        프로세스:
        1. account_no 생성 (SELECT MAX + 1)
        2. stat_nation 생성 (user_no는 auto increment)
        3. 초기 자원 생성
        4. 초기 건물 생성
        5. DB Commit
        
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
            
            # 1. account_no 생성 (SELECT MAX + 1)
            account_result = user_init_db.generate_next_account_no()
            if not account_result['success']:
                return account_result
            
            account_no = account_result['data']['account_no']
            self.logger.debug(f"Generated account_no: {account_no}")
            
            # 2. stat_nation 생성 (user_no는 auto increment)
            stat_result = user_init_db.create_stat_nation(account_no)
            if not stat_result['success']:
                self.db_manager.db.rollback()
                return stat_result
            
            user_no = stat_result['data']['user_no']
            self.logger.debug(f"Created stat_nation: user_no={user_no}, account_no={account_no}")
            
            # 3. 초기 자원 생성
            resources_result = user_init_db.create_resources(
                user_no, 
                self.INITIAL_CONFIG["resources"]
            )
            if not resources_result['success']:
                self.logger.error(f"Failed to create resources: {resources_result['message']}")
                self.db_manager.db.rollback()
                return resources_result
            
            # 4. 초기 건물 생성
            for building_config in self.INITIAL_CONFIG["buildings"]:
                building_result = user_init_db.create_building(user_no, building_config)
                if not building_result['success']:
                    self.logger.error(f"Failed to create building: {building_result['message']}")
                    self.db_manager.db.rollback()
                    return building_result
            
            # 5. DB Commit
            self.db_manager.db.commit()
            
            self.logger.info(
                f"New user created successfully: "
                f"account_no={account_no}, user_no={user_no}"
            )
            
            return {
                "success": True,
                "message": "User created successfully",
                "data": {
                    "user_no": user_no,
                    "account_no": account_no
                }
            }
            
        except Exception as e:
            self.db_manager.db.rollback()
            self.logger.error(f"Error creating new user: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {}
            }
    
    async def create_multiple_users(self, count: int) -> Dict[str, Any]:
        """
        여러 유저를 한 번에 생성 (배치 처리)
        
        Args:
            count: 생성할 유저 수
            
        Returns:
            {"success": bool, "message": str, "data": {"users": list}}
        """
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            created_users = []
            
            for i in range(count):
                # 1. account_no 생성
                account_result = user_init_db.generate_next_account_no()
                if not account_result['success']:
                    self.db_manager.db.rollback()
                    return account_result
                
                account_no = account_result['data']['account_no']
                
                # 2. stat_nation 생성
                stat_result = user_init_db.create_stat_nation(account_no)
                if not stat_result['success']:
                    self.db_manager.db.rollback()
                    return stat_result
                
                user_no = stat_result['data']['user_no']
                
                # 3. 자원 생성
                resources_result = user_init_db.create_resources(
                    user_no,
                    self.INITIAL_CONFIG["resources"]
                )
                if not resources_result['success']:
                    self.db_manager.db.rollback()
                    return resources_result
                
                # 4. 건물 생성 (배치)
                building_result = user_init_db.create_batch_buildings(
                    user_no,
                    self.INITIAL_CONFIG["buildings"]
                )
                if not building_result['success']:
                    self.db_manager.db.rollback()
                    return building_result
                
                created_users.append({
                    "account_no": account_no,
                    "user_no": user_no
                })
                
                # 진행률 로그 (10%마다)
                if (i + 1) % max(1, count // 10) == 0:
                    self.logger.info(f"Progress: {i + 1}/{count} users created")
            
            # DB Commit
            self.db_manager.db.commit()
            
            self.logger.info(f"Created {count} users successfully")
            
            return {
                "success": True,
                "message": f"Created {count} users",
                "data": {"users": created_users}
            }
            
        except Exception as e:
            self.db_manager.db.rollback()
            self.logger.error(f"Error creating multiple users: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def check_user_exists(self, account_no: int) -> bool:
        """
        계정번호로 유저 존재 여부 확인
        
        Args:
            account_no: 계정 번호
            
        Returns:
            bool: 존재 여부
        """
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.check_user_exists(account_no)
            
            if result['success']:
                return result['data'].get('exists', False)
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking user existence: {e}")
            return False
    
    async def get_user_no_by_account(self, account_no: int) -> Optional[int]:
        """
        계정번호로 user_no 조회
        
        Args:
            account_no: 계정 번호
            
        Returns:
            int or None: user_no
        """
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.get_user_by_account_no(account_no)
            
            if result['success']:
                return result['data'].get('user_no')
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting user_no: {e}")
            return None
    
    async def get_user_info(self, account_no: int) -> Optional[Dict[str, Any]]:
        """
        계정번호로 유저 정보 조회
        
        Args:
            account_no: 계정 번호
            
        Returns:
            dict or None: 유저 정보
        """
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.get_user_by_account_no(account_no)
            
            if result['success']:
                return result['data']
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting user info: {e}")
            return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        현재 시스템 통계 조회
        
        Returns:
            {"success": bool, "message": str, "data": dict}
        """
        try:
            user_init_db = self.db_manager.get_user_init_manager()
            
            # 최대 ID 조회
            max_ids = user_init_db.get_max_ids()
            
            # 전체 유저 수
            total_count = user_init_db.get_total_user_count()
            
            # 최근 유저 목록
            recent_users = user_init_db.get_recent_users(5)
            
            return {
                "success": True,
                "message": "Stats retrieved",
                "data": {
                    "max_account_no": max_ids['data']['max_account_no'] if max_ids['success'] else 0,
                    "max_user_no": max_ids['data']['max_user_no'] if max_ids['success'] else 0,
                    "total_users": total_count['data']['total_count'] if total_count['success'] else 0,
                    "recent_users": recent_users['data'].get('users', []) if recent_users['success'] else []
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting stats: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }