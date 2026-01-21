from datetime import datetime
from typing import Optional, Dict, Any, List
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType
import logging
import asyncio


class AllianceRedisManager:
    """
    연맹 전용 Redis 관리자
    
    저장 구조:
        alliance:{id}:info         → 연맹 기본 정보 (String/JSON)
        alliance:{id}:members      → 멤버 목록 (Hash)
        alliance:{id}:applications → 가입 신청 목록 (Hash)
        user:{user_no}:alliance    → 유저의 연맹 정보 (String/JSON)
        alliance:name:{name}       → 이름 → ID 매핑 (String)
        alliance:list              → 전체 연맹 ID 목록 (Set)
    """
    
    LOCK_TIMEOUT = 10  # 락 타임아웃 (초)
    LOCK_RETRY_DELAY = 0.1  # 락 재시도 간격 (초)
    LOCK_MAX_RETRIES = 50  # 최대 재시도 횟수
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.ALLIANCE)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.cache_expire_time = 86400  # 24시간

    # ==================== 키 생성 ====================
    
    def _get_alliance_info_key(self, alliance_id: int) -> str:
        return f"alliance:{alliance_id}:info"
    
    def _get_alliance_members_key(self, alliance_id: int) -> str:
        return f"alliance:{alliance_id}:members"
    
    def _get_alliance_applications_key(self, alliance_id: int) -> str:
        return f"alliance:{alliance_id}:applications"
    
    def _get_user_alliance_key(self, user_no: int) -> str:
        return f"user:{user_no}:alliance"
    
    def _get_alliance_name_key(self, name: str) -> str:
        return f"alliance:name:{name}"
    
    def _get_alliance_lock_key(self, alliance_id: int) -> str:
        return f"alliance:{alliance_id}:lock"
    
    def _get_alliance_list_key(self) -> str:
        return "alliance:list"
    
    def _get_alliance_id_counter_key(self) -> str:
        return "alliance:id_counter"

    # ==================== 분산 락 ====================
    
    async def acquire_lock(self, alliance_id: int) -> bool:
        """연맹 락 획득 (동시성 제어)"""
        lock_key = self._get_alliance_lock_key(alliance_id)
        
        for _ in range(self.LOCK_MAX_RETRIES):
            # SETNX로 락 획득 시도
            acquired = await self.redis_client.set(
                lock_key, "locked", 
                nx=True, ex=self.LOCK_TIMEOUT
            )
            
            if acquired:
                self.logger.debug(f"Lock acquired for alliance {alliance_id}")
                return True
            
            # 락 획득 실패 시 대기 후 재시도
            await asyncio.sleep(self.LOCK_RETRY_DELAY)
        
        self.logger.warning(f"Failed to acquire lock for alliance {alliance_id}")
        return False
    
    async def release_lock(self, alliance_id: int) -> bool:
        """연맹 락 해제"""
        lock_key = self._get_alliance_lock_key(alliance_id)
        await self.redis_client.delete(lock_key)
        self.logger.debug(f"Lock released for alliance {alliance_id}")
        return True

    # ==================== 연맹 ID 생성 ====================
    
    async def generate_alliance_id(self) -> int:
        """새 연맹 ID 생성 (원자적 증가)"""
        counter_key = self._get_alliance_id_counter_key()
        new_id = await self.redis_client.incr(counter_key)
        return new_id

    # ==================== 연맹 정보 ====================
    
    async def get_alliance_info(self, alliance_id: int) -> Optional[Dict[str, Any]]:
        """연맹 정보 조회"""
        try:
            info_key = self._get_alliance_info_key(alliance_id)
            return await self.cache_manager.get_data(info_key)
        except Exception as e:
            self.logger.error(f"Error getting alliance info: {e}")
            return None
    
    async def set_alliance_info(self, alliance_id: int, info: Dict[str, Any]) -> bool:
        """연맹 정보 저장"""
        try:
            info_key = self._get_alliance_info_key(alliance_id)
            return await self.cache_manager.set_data(
                info_key, info, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting alliance info: {e}")
            return False
    
    async def delete_alliance_info(self, alliance_id: int) -> bool:
        """연맹 정보 삭제"""
        try:
            info_key = self._get_alliance_info_key(alliance_id)
            return await self.cache_manager.delete_data(info_key)
        except Exception as e:
            self.logger.error(f"Error deleting alliance info: {e}")
            return False

    # ==================== 멤버 관리 ====================
    
    async def get_alliance_members(self, alliance_id: int) -> Dict[str, Dict]:
        """연맹 멤버 목록 조회"""
        try:
            members_key = self._get_alliance_members_key(alliance_id)
            members = await self.cache_manager.get_hash_data(members_key)
            return members or {}
        except Exception as e:
            self.logger.error(f"Error getting alliance members: {e}")
            return {}
    
    async def get_member_count(self, alliance_id: int) -> int:
        """연맹 멤버 수 조회"""
        try:
            members_key = self._get_alliance_members_key(alliance_id)
            return await self.cache_manager.get_hash_length(members_key) or 0
        except Exception as e:
            self.logger.error(f"Error getting member count: {e}")
            return 0
    
    async def add_member(self, alliance_id: int, user_no: int, member_data: Dict) -> bool:
        """멤버 추가"""
        try:
            members_key = self._get_alliance_members_key(alliance_id)
            return await self.cache_manager.set_hash_field(
                members_key, str(user_no), member_data,
                expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error adding member: {e}")
            return False
    
    async def remove_member(self, alliance_id: int, user_no: int) -> bool:
        """멤버 제거"""
        try:
            members_key = self._get_alliance_members_key(alliance_id)
            return await self.cache_manager.delete_hash_field(members_key, str(user_no))
        except Exception as e:
            self.logger.error(f"Error removing member: {e}")
            return False
    
    async def get_member(self, alliance_id: int, user_no: int) -> Optional[Dict]:
        """특정 멤버 정보 조회"""
        try:
            members_key = self._get_alliance_members_key(alliance_id)
            return await self.cache_manager.get_hash_field(members_key, str(user_no))
        except Exception as e:
            self.logger.error(f"Error getting member: {e}")
            return None
    
    async def update_member(self, alliance_id: int, user_no: int, member_data: Dict) -> bool:
        """멤버 정보 업데이트"""
        return await self.add_member(alliance_id, user_no, member_data)
    
    async def delete_all_members(self, alliance_id: int) -> bool:
        """모든 멤버 삭제"""
        try:
            members_key = self._get_alliance_members_key(alliance_id)
            return await self.cache_manager.delete_data(members_key)
        except Exception as e:
            self.logger.error(f"Error deleting all members: {e}")
            return False

    # ==================== 유저 연맹 정보 ====================
    
    async def get_user_alliance(self, user_no: int) -> Optional[Dict[str, Any]]:
        """유저의 연맹 정보 조회"""
        try:
            user_key = self._get_user_alliance_key(user_no)
            return await self.cache_manager.get_data(user_key)
        except Exception as e:
            self.logger.error(f"Error getting user alliance: {e}")
            return None
    
    async def set_user_alliance(self, user_no: int, alliance_data: Dict[str, Any]) -> bool:
        """유저의 연맹 정보 저장"""
        try:
            user_key = self._get_user_alliance_key(user_no)
            return await self.cache_manager.set_data(
                user_key, alliance_data, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting user alliance: {e}")
            return False
    
    async def delete_user_alliance(self, user_no: int) -> bool:
        """유저의 연맹 정보 삭제"""
        try:
            user_key = self._get_user_alliance_key(user_no)
            return await self.cache_manager.delete_data(user_key)
        except Exception as e:
            self.logger.error(f"Error deleting user alliance: {e}")
            return False

    # ==================== 연맹 이름 매핑 ====================
    
    async def get_alliance_id_by_name(self, name: str) -> Optional[int]:
        """이름으로 연맹 ID 조회"""
        try:
            name_key = self._get_alliance_name_key(name)
            alliance_id = await self.cache_manager.get_data(name_key)
            return int(alliance_id) if alliance_id else None
        except Exception as e:
            self.logger.error(f"Error getting alliance by name: {e}")
            return None
    
    async def set_alliance_name_mapping(self, name: str, alliance_id: int) -> bool:
        """연맹 이름 → ID 매핑 저장"""
        try:
            name_key = self._get_alliance_name_key(name)
            return await self.cache_manager.set_data(
                name_key, alliance_id, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting alliance name mapping: {e}")
            return False
    
    async def delete_alliance_name_mapping(self, name: str) -> bool:
        """연맹 이름 매핑 삭제"""
        try:
            name_key = self._get_alliance_name_key(name)
            return await self.cache_manager.delete_data(name_key)
        except Exception as e:
            self.logger.error(f"Error deleting alliance name mapping: {e}")
            return False

    # ==================== 가입 신청 관리 ====================
    
    async def get_applications(self, alliance_id: int) -> Dict[str, Dict]:
        """가입 신청 목록 조회"""
        try:
            app_key = self._get_alliance_applications_key(alliance_id)
            apps = await self.cache_manager.get_hash_data(app_key)
            return apps or {}
        except Exception as e:
            self.logger.error(f"Error getting applications: {e}")
            return {}
    
    async def add_application(self, alliance_id: int, user_no: int, app_data: Dict) -> bool:
        """가입 신청 추가"""
        try:
            app_key = self._get_alliance_applications_key(alliance_id)
            return await self.cache_manager.set_hash_field(
                app_key, str(user_no), app_data,
                expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error adding application: {e}")
            return False
    
    async def remove_application(self, alliance_id: int, user_no: int) -> bool:
        """가입 신청 제거"""
        try:
            app_key = self._get_alliance_applications_key(alliance_id)
            return await self.cache_manager.delete_hash_field(app_key, str(user_no))
        except Exception as e:
            self.logger.error(f"Error removing application: {e}")
            return False
    
    async def get_application(self, alliance_id: int, user_no: int) -> Optional[Dict]:
        """특정 가입 신청 조회"""
        try:
            app_key = self._get_alliance_applications_key(alliance_id)
            return await self.cache_manager.get_hash_field(app_key, str(user_no))
        except Exception as e:
            self.logger.error(f"Error getting application: {e}")
            return None
    
    async def delete_all_applications(self, alliance_id: int) -> bool:
        """모든 가입 신청 삭제"""
        try:
            app_key = self._get_alliance_applications_key(alliance_id)
            return await self.cache_manager.delete_data(app_key)
        except Exception as e:
            self.logger.error(f"Error deleting all applications: {e}")
            return False

    # ==================== 연맹 목록 관리 ====================
    
    async def add_to_alliance_list(self, alliance_id: int) -> bool:
        """연맹 목록에 추가"""
        try:
            list_key = self._get_alliance_list_key()
            await self.redis_client.sadd(list_key, alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error adding to alliance list: {e}")
            return False
    
    async def remove_from_alliance_list(self, alliance_id: int) -> bool:
        """연맹 목록에서 제거"""
        try:
            list_key = self._get_alliance_list_key()
            await self.redis_client.srem(list_key, alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error removing from alliance list: {e}")
            return False
    
    async def get_all_alliance_ids(self) -> List[int]:
        """전체 연맹 ID 목록 조회"""
        try:
            list_key = self._get_alliance_list_key()
            ids = await self.redis_client.smembers(list_key)
            return [int(id) for id in ids] if ids else []
        except Exception as e:
            self.logger.error(f"Error getting alliance list: {e}")
            return []

    # ==================== 검색 ====================
    
    async def search_alliances(self, keyword: str, limit: int = 20) -> List[Dict]:
        """연맹 검색 (이름에 키워드 포함)"""
        try:
            all_ids = await self.get_all_alliance_ids()
            results = []
            
            for alliance_id in all_ids:
                info = await self.get_alliance_info(alliance_id)
                if info and keyword.lower() in info.get('name', '').lower():
                    member_count = await self.get_member_count(alliance_id)
                    results.append({
                        **info,
                        "member_count": member_count
                    })
                    
                    if len(results) >= limit:
                        break
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error searching alliances: {e}")
            return []
