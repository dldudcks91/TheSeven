from typing import Optional, Dict, Any
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType
import logging


class NationRedisManager:
    """
    유저 기본 프로필 Redis 관리자
    
    저장 구조:
        user_data:{user_no}:nation → 유저 기본 프로필 (String/JSON)
        {
            "user_no": 1001,
            "nickname": "Player1",
            "level": 15,
            "power": 50000,
            "alliance_no": null,
            "alliance_position": null
        }
    """
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.NATION)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cache_expire_time = 86400  # 24시간

    

    # ==================== 프로필 CRUD ====================
    
    async def get_cached_nation(self, user_no: int) -> Optional[Dict[str, Any]]:
        """유저 프로필 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            nation = await self.cache_manager.get_hash_data(hash_key)
            
            if nation:
                print(f"Cache hit: Retrieved {len(nation)} nation for user {user_no}")
                return nation
            
            print(f"Cache miss: No cached nation for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached nation for user {user_no}: {e}")
            return None
    

    
        
    async def cache_user_nation_data(self, user_no: int, data: Dict[str, Any]) -> bool:
        """유저 프로필 저장"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            success = await self.cache_manager.set_hash_data(
                hash_key, data, expire_time=self.cache_expire_time
            )
            if success:
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error setting nation: {e}")
            return False
    
    async def delete_nation(self, user_no: int) -> bool:
        """유저 프로필 삭제"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            return await self.cache_manager.delete_data(hash_key)
        except Exception as e:
            self.logger.error(f"Error deleting nation: {e}")
            return False

    # ==================== 필드 단위 업데이트 ====================
    
    async def update_field(self, user_no: int, field: str, value: Any) -> bool:
        """특정 필드만 업데이트"""
        try:
            data = await self.get_cached_nation(user_no)
            if not data:
                return False
            data[field] = value
            return await self.cache_user_nation_data(user_no, data)
        except Exception as e:
            self.logger.error(f"Error updating field {field}: {e}")
            return False
    
    async def update_fields(self, user_no: int, fields: Dict[str, Any]) -> bool:
        """여러 필드 한번에 업데이트"""
        try:
            data = await self.get_cached_nation(user_no)
            if not data:
                return False
            data.update(fields)
            return await self.cache_user_nation_data(user_no, data)
        except Exception as e:
            self.logger.error(f"Error updating fields: {e}")
            return False

    # ==================== 연맹 관련 편의 메서드 ====================
    
    async def set_alliance_info(self, user_no: int, alliance_no: int, position: int) -> bool:
        """연맹 가입 정보 업데이트"""
        return await self.update_fields(user_no, {
            "alliance_no": alliance_no,
            "alliance_position": position
        })
    
    async def clear_alliance_info(self, user_no: int) -> bool:
        """연맹 정보 초기화 (탈퇴/추방 시)"""
        return await self.update_fields(user_no, {
            "alliance_no": None,
            "alliance_position": None
        })
    
    async def get_alliance_no(self, user_no: int) -> Optional[int]:
        """유저의 연맹 ID만 조회"""
        data = await self.get_nation(user_no)
        if data:
            return data.get("alliance_no")
        return None