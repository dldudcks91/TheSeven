from sqlalchemy.orm import Session
import models
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from services.user_init_redis_manager import UserInitRedisManager
from datetime import datetime
import logging
from typing import Dict, Any, Optional


class UserInitManager:
    """
    신규 유저 초기화 Manager
    Redis에서 ID 생성, DB에 데이터 저장, Redis에 캐싱
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
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        # UserInitRedisManager 초기화
        self.user_init_redis = UserInitRedisManager(redis_manager.redis_client)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
    
    async def initialize(self) -> Dict[str, Any]:
        """
        서비스 시작시 초기화
        DB의 현재 최대값으로 Redis 초기화
        """
        try:
            # Redis 초기화 (DB의 최대값 동기화)
            result = await self.user_init_redis.initialize_from_db(self.db_manager)
            
            if result['success']:
                self._initialized = True
                self.logger.info(
                    f"UserInitManager initialized successfully. "
                    f"Current max - account_no: {result['data']['account_no']}, "
                    f"user_no: {result['data']['user_no']}"
                )
            else:
                self.logger.error(f"Failed to initialize UserInitManager: {result['message']}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def create_new_user(self) -> Dict[str, Any]:
        """
        신규 유저 생성 - Redis에서 ID 발급 후 DB 저장
        
        Returns:
            {
                "success": bool,
                "message": str,
                "data": {"user_no": int, "account_no": int}
            }
        """
        # 초기화 체크
        if not self._initialized:
            await self.initialize()
        
        try:
            # 1. Redis에서 원자적으로 ID 발급 (동시성 문제 완벽 해결!)
            id_result = await self.user_init_redis.generate_next_ids()
            
            if not id_result['success']:
                self.logger.error(f"Failed to generate IDs: {id_result['message']}")
                return id_result
            
            account_no = id_result['data']['account_no']
            user_no = id_result['data']['user_no']
            
            self.logger.info(f"Generated IDs from Redis: account_no={account_no}, user_no={user_no}")
            
            # 2. DB Manager 가져오기
            user_init_db = self.db_manager.get_user_init_manager()
            
            # 3. stat_nation 생성 (Redis에서 생성된 ID 사용)
            stat_result = user_init_db.create_stat_nation(account_no, user_no)
            if not stat_result['success']:
                self.logger.error(f"Failed to create stat_nation: {stat_result['message']}")
                self.db_manager.rollback()
                return stat_result
            
            # 4. 초기 자원 생성
            resources_result = user_init_db.create_resources(
                user_no, 
                self.INITIAL_CONFIG["resources"]
            )
            if not resources_result['success']:
                self.logger.error(f"Failed to create resources: {resources_result['message']}")
                self.db_manager.rollback()
                return resources_result
            
            # 5. 초기 건물 생성
            for building_config in self.INITIAL_CONFIG["buildings"]:
                building_result = user_init_db.create_building(user_no, building_config)
                if not building_result['success']:
                    self.logger.error(f"Failed to create building: {building_result['message']}")
                    self.db_manager.rollback()
                    return building_result
            
            # 6. DB Commit
            self.db_manager.commit()
            
            # 7. Redis에 유저 데이터 캐싱
            await self.user_init_redis.cache_user_data(user_no, account_no)
            
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
            self.db_manager.rollback()
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
        """
        # 초기화 체크
        if not self._initialized:
            await self.initialize()
        
        try:
            # 1. ID 범위 예약
            reservation = await self.user_init_redis.reserve_id_range(count)
            if not reservation['success']:
                return reservation
            
            account_range = reservation['data']['account_no_range']
            user_range = reservation['data']['user_no_range']
            
            user_init_db = self.db_manager.get_user_init_manager()
            created_users = []
            
            # 2. 배치 처리로 유저 생성
            for i in range(count):
                account_no = account_range['start'] + i
                user_no = user_range['start'] + i
                
                # stat_nation 생성
                stat_result = user_init_db.create_stat_nation(account_no, user_no)
                if not stat_result['success']:
                    self.db_manager.rollback()
                    return stat_result
                
                # 자원 생성
                resources_result = user_init_db.create_resources(
                    user_no,
                    self.INITIAL_CONFIG["resources"]
                )
                if not resources_result['success']:
                    self.db_manager.rollback()
                    return resources_result
                
                # 건물 생성 (배치)
                building_result = user_init_db.create_batch_buildings(
                    user_no,
                    self.INITIAL_CONFIG["buildings"]
                )
                if not building_result['success']:
                    self.db_manager.rollback()
                    return building_result
                
                created_users.append({
                    "account_no": account_no,
                    "user_no": user_no
                })
                
                # Redis 캐싱 (비동기)
                await self.user_init_redis.cache_user_data(user_no, account_no)
            
            # 3. DB Commit
            self.db_manager.commit()
            
            self.logger.info(f"Created {count} users successfully")
            
            return {
                "success": True,
                "message": f"Created {count} users",
                "data": {"users": created_users}
            }
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error creating multiple users: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def check_user_exists(self, account_no: int) -> bool:
        """
        계정번호로 유저 존재 여부 확인
        Redis 캐시 우선 확인 후 DB 조회
        """
        try:
            # 1. Redis 캐시에서 먼저 확인
            cached_user_no = await self.user_init_redis.get_cached_user_no(account_no)
            
            if cached_user_no is not None:
                return True
            
            # 2. DB 확인
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.check_user_exists(account_no)
            
            if result['success'] and result['data'].get('exists'):
                # 캐시 갱신
                user_no = result['data']['user_no']
                await self.user_init_redis.cache_user_data(user_no, account_no)
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking user existence: {e}")
            return False
    
    async def get_user_no_by_account(self, account_no: int) -> Optional[int]:
        """
        계정번호로 user_no 조회
        Redis 캐시 활용
        """
        try:
            # 1. Redis 캐시에서 먼저 확인
            cached_user_no = await self.user_init_redis.get_cached_user_no(account_no)
            
            if cached_user_no is not None:
                return cached_user_no
            
            # 2. DB에서 조회
            user_init_db = self.db_manager.get_user_init_manager()
            result = user_init_db.get_user_by_account_no(account_no)
            
            if result['success']:
                user_no = result['data'].get('user_no')
                if user_no:
                    # 캐시 갱신
                    await self.user_init_redis.cache_user_data(user_no, account_no)
                return user_no
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting user_no: {e}")
            return None
    
    async def get_user_data(self, user_no: int) -> Optional[Dict[str, Any]]:
        """
        user_no로 유저 데이터 조회
        Redis 캐시 우선
        """
        try:
            # Redis에서 캐시된 데이터 조회
            cached_data = await self.user_init_redis.get_cached_user_data(user_no)
            
            if cached_data:
                return cached_data
            
            # DB 조회는 별도 메서드나 Manager에서 처리
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting user data: {e}")
            return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        현재 시스템 통계 조회
        """
        try:
            # Redis에서 현재 카운터 값
            current_ids = await self.user_init_redis.get_current_values()
            
            # DB에서 최근 유저 정보
            user_init_db = self.db_manager.get_user_init_manager()
            recent_users = user_init_db.get_recent_users(5)
            
            return {
                "success": True,
                "message": "Stats retrieved",
                "data": {
                    "total_accounts": current_ids["account_no"],
                    "total_users": current_ids["user_no"],
                    "recent_users": recent_users['data'].get('users', []) if recent_users['success'] else [],
                    "redis_connected": await self.redis_manager.redis_client.ping()
                }
            }
        except Exception as e:
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def recover_from_failure(self) -> Dict[str, Any]:
        """
        장애 복구 - Redis를 백업값으로 복구
        """
        try:
            result = await self.user_init_redis.reset_to_backup()
            
            if result['success']:
                self.logger.info(f"Recovered to backup values: {result['data']}")
            else:
                self.logger.error(f"Failed to recover: {result['message']}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error during recovery: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }