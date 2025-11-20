import redis.asyncio as redis
from typing import Optional, Dict, Any
import logging
from datetime import datetime


class UserInitRedisManager:
    """유저 초기화 전용 Redis 관리자 - ID 생성 및 캐싱 담당"""
    
    # Redis 키 정의
    ACCOUNT_NO_KEY = "game:next:account_no"
    USER_NO_KEY = "game:next:user_no"
    
    # 백업용 키 (장애 대비)
    BACKUP_ACCOUNT_NO_KEY = "game:backup:account_no"
    BACKUP_USER_NO_KEY = "game:backup:user_no"
    
    # 유저 캐시 키 패턴
    USER_CACHE_KEY = "user:{user_no}"
    ACCOUNT_MAPPING_KEY = "account:{account_no}"
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def initialize_from_db(self, db_manager) -> Dict[str, Any]:
        """
        DB에서 현재 최대값을 읽어와 Redis 초기화
        서버 시작시 한 번만 실행
        """
        try:
            from sqlalchemy import func
            import models
            
            # DB에서 현재 최대값 조회
            max_account_no = db_manager.db.query(
                func.max(models.StatNation.account_no)
            ).scalar() or 0
            
            max_user_no = db_manager.db.query(
                func.max(models.StatNation.user_no)
            ).scalar() or 0
            
            # Redis에 초기값 설정 (이미 값이 있으면 설정하지 않음)
            await self.redis.set(
                self.ACCOUNT_NO_KEY, 
                max_account_no, 
                nx=True  # 키가 없을 때만 설정
            )
            
            await self.redis.set(
                self.USER_NO_KEY,
                max_user_no,
                nx=True  # 키가 없을 때만 설정
            )
            
            # 백업값도 설정
            await self.redis.set(self.BACKUP_ACCOUNT_NO_KEY, max_account_no)
            await self.redis.set(self.BACKUP_USER_NO_KEY, max_user_no)
            
            self.logger.info(
                f"UserInitRedisManager initialized: "
                f"account_no={max_account_no}, user_no={max_user_no}"
            )
            
            return {
                "success": True,
                "message": "Redis manager initialized",
                "data": {
                    "account_no": max_account_no,
                    "user_no": max_user_no
                }
            }
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Redis manager: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def generate_next_account_no(self) -> Dict[str, Any]:
        """
        다음 account_no 발급 (원자적 연산)
        
        Returns:
            {"success": bool, "message": str, "data": {"account_no": int}}
        """
        try:
            # INCR은 원자적 연산 - 동시에 여러 요청이 와도 각각 다른 값 보장
            next_value = await self.redis.incr(self.ACCOUNT_NO_KEY)
            
            # 백업 업데이트 (비동기)
            await self.redis.set(self.BACKUP_ACCOUNT_NO_KEY, next_value)
            
            self.logger.debug(f"Generated account_no: {next_value}")
            
            return {
                "success": True,
                "message": f"Generated account_no: {next_value}",
                "data": {"account_no": next_value}
            }
            
        except redis.RedisError as e:
            self.logger.error(f"Redis error generating account_no: {e}")
            return {
                "success": False,
                "message": f"Redis error: {str(e)}",
                "data": {}
            }
    
    async def generate_next_user_no(self) -> Dict[str, Any]:
        """
        다음 user_no 발급 (원자적 연산)
        
        Returns:
            {"success": bool, "message": str, "data": {"user_no": int}}
        """
        try:
            # INCR은 원자적 연산
            next_value = await self.redis.incr(self.USER_NO_KEY)
            
            # 백업 업데이트
            await self.redis.set(self.BACKUP_USER_NO_KEY, next_value)
            
            self.logger.debug(f"Generated user_no: {next_value}")
            
            return {
                "success": True,
                "message": f"Generated user_no: {next_value}",
                "data": {"user_no": next_value}
            }
            
        except redis.RedisError as e:
            self.logger.error(f"Redis error generating user_no: {e}")
            return {
                "success": False,
                "message": f"Redis error: {str(e)}",
                "data": {}
            }
    
    async def generate_next_ids(self) -> Dict[str, Any]:
        """
        account_no와 user_no를 한 번에 발급 (파이프라인 사용)
        
        Returns:
            {"success": bool, "message": str, "data": {"account_no": int, "user_no": int}}
        """
        try:
            # Redis 파이프라인으로 여러 명령을 한 번에 실행
            async with self.redis.pipeline() as pipe:
                pipe.incr(self.ACCOUNT_NO_KEY)
                pipe.incr(self.USER_NO_KEY)
                results = await pipe.execute()
            
            account_no = results[0]
            user_no = results[1]
            
            # 백업 업데이트 (별도 파이프라인)
            async with self.redis.pipeline() as pipe:
                pipe.set(self.BACKUP_ACCOUNT_NO_KEY, account_no)
                pipe.set(self.BACKUP_USER_NO_KEY, user_no)
                await pipe.execute()
            
            self.logger.debug(
                f"Generated IDs: account_no={account_no}, user_no={user_no}"
            )
            
            return {
                "success": True,
                "message": "IDs generated successfully",
                "data": {
                    "account_no": account_no,
                    "user_no": user_no
                }
            }
            
        except redis.RedisError as e:
            self.logger.error(f"Redis error generating IDs: {e}")
            return {
                "success": False,
                "message": f"Redis error: {str(e)}",
                "data": {}
            }
    
    async def cache_user_data(self, user_no: int, account_no: int) -> Dict[str, Any]:
        """
        Redis에 유저 기본 정보 캐싱
        
        Args:
            user_no: 유저 번호
            account_no: 계정 번호
        """
        try:
            user_key = self.USER_CACHE_KEY.format(user_no=user_no)
            account_key = self.ACCOUNT_MAPPING_KEY.format(account_no=account_no)
            
            user_data = {
                "user_no": user_no,
                "account_no": account_no,
                "created_at": datetime.utcnow().isoformat()
            }
            
            # Hash로 유저 정보 저장
            await self.redis.hset(
                user_key,
                mapping=user_data
            )
            
            # account_no -> user_no 매핑
            await self.redis.set(account_key, user_no)
            
            # 만료 시간 설정 (7일)
            await self.redis.expire(user_key, 604800)
            await self.redis.expire(account_key, 604800)
            
            self.logger.debug(f"Cached user data: user_no={user_no}, account_no={account_no}")
            
            return {
                "success": True,
                "message": "User data cached",
                "data": user_data
            }
            
        except Exception as e:
            self.logger.warning(f"Failed to cache user data: {e}")
            return {
                "success": False,
                "message": f"Cache error: {str(e)}",
                "data": {}
            }
    
    async def get_cached_user_no(self, account_no: int) -> Optional[int]:
        """
        캐시에서 account_no로 user_no 조회
        
        Args:
            account_no: 계정 번호
            
        Returns:
            user_no or None
        """
        try:
            account_key = self.ACCOUNT_MAPPING_KEY.format(account_no=account_no)
            cached_user_no = await self.redis.get(account_key)
            
            if cached_user_no:
                return int(cached_user_no)
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting cached user_no: {e}")
            return None
    
    async def get_cached_user_data(self, user_no: int) -> Optional[Dict[str, Any]]:
        """
        캐시에서 유저 데이터 조회
        
        Args:
            user_no: 유저 번호
            
        Returns:
            유저 데이터 딕셔너리 or None
        """
        try:
            user_key = self.USER_CACHE_KEY.format(user_no=user_no)
            user_data = await self.redis.hgetall(user_key)
            
            if user_data:
                # bytes를 string으로 변환
                return {
                    k.decode() if isinstance(k, bytes) else k: 
                    v.decode() if isinstance(v, bytes) else v 
                    for k, v in user_data.items()
                }
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting cached user data: {e}")
            return None
    
    async def reserve_id_range(self, count: int = 100) -> Dict[str, Any]:
        """
        ID 범위를 미리 예약 (대량 생성시 사용)
        
        Args:
            count: 예약할 ID 개수
        """
        try:
            # 현재 값 가져오기
            current_account_no = int(await self.redis.get(self.ACCOUNT_NO_KEY) or 0)
            current_user_no = int(await self.redis.get(self.USER_NO_KEY) or 0)
            
            # 범위만큼 증가
            new_account_no = await self.redis.incrby(self.ACCOUNT_NO_KEY, count)
            new_user_no = await self.redis.incrby(self.USER_NO_KEY, count)
            
            return {
                "success": True,
                "message": f"Reserved {count} IDs",
                "data": {
                    "account_no_range": {
                        "start": current_account_no + 1,
                        "end": new_account_no
                    },
                    "user_no_range": {
                        "start": current_user_no + 1,
                        "end": new_user_no
                    }
                }
            }
            
        except redis.RedisError as e:
            self.logger.error(f"Redis error reserving ID range: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def get_current_values(self) -> Dict[str, Any]:
        """
        현재 카운터 값 조회 (디버깅/통계용)
        
        Returns:
            {"account_no": int, "user_no": int}
        """
        try:
            account_no = await self.redis.get(self.ACCOUNT_NO_KEY)
            user_no = await self.redis.get(self.USER_NO_KEY)
            
            return {
                "account_no": int(account_no) if account_no else 0,
                "user_no": int(user_no) if user_no else 0
            }
        except Exception as e:
            self.logger.error(f"Error getting current values: {e}")
            return {"account_no": 0, "user_no": 0}
    
    async def reset_to_backup(self) -> Dict[str, Any]:
        """백업값으로 복구 (장애 대응)"""
        try:
            backup_account = await self.redis.get(self.BACKUP_ACCOUNT_NO_KEY)
            backup_user = await self.redis.get(self.BACKUP_USER_NO_KEY)
            
            if backup_account:
                await self.redis.set(self.ACCOUNT_NO_KEY, backup_account)
            if backup_user:
                await self.redis.set(self.USER_NO_KEY, backup_user)
            
            return {
                "success": True,
                "message": "Reset to backup values",
                "data": {
                    "account_no": int(backup_account) if backup_account else 0,
                    "user_no": int(backup_user) if backup_user else 0
                }
            }
        except Exception as e:
            self.logger.error(f"Error resetting to backup: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }
    
    async def clear_user_cache(self, user_no: int, account_no: int) -> Dict[str, Any]:
        """
        특정 유저의 캐시 삭제
        
        Args:
            user_no: 유저 번호
            account_no: 계정 번호
        """
        try:
            user_key = self.USER_CACHE_KEY.format(user_no=user_no)
            account_key = self.ACCOUNT_MAPPING_KEY.format(account_no=account_no)
            
            # 캐시 삭제
            deleted_count = 0
            deleted_count += await self.redis.delete(user_key)
            deleted_count += await self.redis.delete(account_key)
            
            return {
                "success": True,
                "message": f"Cleared {deleted_count} cache entries",
                "data": {"deleted_count": deleted_count}
            }
            
        except Exception as e:
            self.logger.error(f"Error clearing user cache: {e}")
            return {
                "success": False,
                "message": str(e),
                "data": {}
            }