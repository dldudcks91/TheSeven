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
        alliance_data:{alliance_id}:info             → 연맹 기본 정보 (String/JSON)
        alliance_data:{alliance_id}:members          → 멤버 목록 (Hash)
        alliance_data:{alliance_id}:applications     → 가입 신청 목록 (Hash)
        alliance_data:{alliance_id}:notice           → 공지사항 (String/JSON)
        alliance_data:{alliance_id}:research         → 연구 진행 상태 (Hash)
        alliance_data:{alliance_id}:active_research  → 현재 활성 연구 (String/JSON)
        alliance_data:name:{name}                    → 이름 → ID 매핑 (String)
        alliance_data:list                           → 전체 연맹 ID 목록 (Set)
    """
    
    LOCK_TIMEOUT = 10
    LOCK_RETRY_DELAY = 0.1
    LOCK_MAX_RETRIES = 50
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.ALLIANCE)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cache_expire_time = 86400  # 24시간

    # ==================== 키 생성 ====================
    
    def _key_info(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:info"
    
    def _key_members(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:members"
    
    def _key_applications(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:applications"
    
    def _key_notice(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:notice"
    
    def _key_research(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:research"
    
    def _key_active_research(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:active_research"
    
    def _key_name_mapping(self, name: str) -> str:
        return f"alliance_data:name:{name}"
    
    def _key_list(self) -> str:
        return "alliance_data:list"
    
    def _key_id_counter(self) -> str:
        return "alliance_data:id_counter"
    
    def _key_lock(self, alliance_id: int) -> str:
        return f"alliance_data:{alliance_id}:lock"

    # ==================== 분산 락 ====================
    
    async def acquire_lock(self, alliance_id: int) -> bool:
        """연맹 락 획득"""
        lock_key = self._key_lock(alliance_id)
        
        for _ in range(self.LOCK_MAX_RETRIES):
            acquired = await self.redis_client.set(
                lock_key, "locked",
                nx=True, ex=self.LOCK_TIMEOUT
            )
            if acquired:
                return True
            await asyncio.sleep(self.LOCK_RETRY_DELAY)
        
        self.logger.warning(f"Failed to acquire lock for alliance {alliance_id}")
        return False
    
    async def release_lock(self, alliance_id: int) -> bool:
        """연맹 락 해제"""
        lock_key = self._key_lock(alliance_id)
        await self.redis_client.delete(lock_key)
        return True

    # ==================== 연맹 ID 생성 ====================
    
    async def generate_alliance_id(self) -> int:
        """새 연맹 ID 생성 (원자적 증가)"""
        return await self.redis_client.incr(self._key_id_counter())

    # ==================== 연맹 정보 ====================
    
    async def get_alliance_info(self, alliance_id: int) -> Optional[Dict[str, Any]]:
        """연맹 정보 조회"""
        try:
            return await self.cache_manager.get_data(self._key_info(alliance_id))
        except Exception as e:
            self.logger.error(f"Error getting alliance info: {e}")
            return None
    
    async def set_alliance_info(self, alliance_id: int, info: Dict[str, Any]) -> bool:
        """연맹 정보 저장"""
        try:
            return await self.cache_manager.set_data(
                self._key_info(alliance_id), info, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting alliance info: {e}")
            return False
    
    async def delete_alliance_info(self, alliance_id: int) -> bool:
        """연맹 정보 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_info(alliance_id))
        except Exception as e:
            self.logger.error(f"Error deleting alliance info: {e}")
            return False

    # ==================== 멤버 관리 ====================
    
    async def get_members(self, alliance_id: int) -> Dict[str, Dict]:
        """멤버 목록 조회"""
        try:
            members = await self.cache_manager.get_hash_data(self._key_members(alliance_id))
            return members or {}
        except Exception as e:
            self.logger.error(f"Error getting members: {e}")
            return {}
    
    async def get_member_count(self, alliance_id: int) -> int:
        """멤버 수 조회"""
        try:
            return await self.cache_manager.get_hash_length(self._key_members(alliance_id)) or 0
        except Exception as e:
            self.logger.error(f"Error getting member count: {e}")
            return 0
    
    async def get_member(self, alliance_id: int, user_no: int) -> Optional[Dict]:
        """특정 멤버 조회"""
        try:
            return await self.cache_manager.get_hash_field(
                self._key_members(alliance_id), str(user_no)
            )
        except Exception as e:
            self.logger.error(f"Error getting member: {e}")
            return None
    
    async def add_member(self, alliance_id: int, user_no: int, member_data: Dict) -> bool:
        """멤버 추가"""
        try:
            return await self.cache_manager.set_hash_field(
                self._key_members(alliance_id), str(user_no), member_data,
                expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error adding member: {e}")
            return False
    
    async def update_member(self, alliance_id: int, user_no: int, member_data: Dict) -> bool:
        """멤버 정보 업데이트"""
        return await self.add_member(alliance_id, user_no, member_data)
    
    async def remove_member(self, alliance_id: int, user_no: int) -> bool:
        """멤버 제거"""
        try:
            return await self.cache_manager.delete_hash_field(
                self._key_members(alliance_id), str(user_no)
            )
        except Exception as e:
            self.logger.error(f"Error removing member: {e}")
            return False
    
    async def delete_all_members(self, alliance_id: int) -> bool:
        """모든 멤버 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_members(alliance_id))
        except Exception as e:
            self.logger.error(f"Error deleting all members: {e}")
            return False

    # ==================== 가입 신청 관리 ====================
    
    async def get_applications(self, alliance_id: int) -> Dict[str, Dict]:
        """가입 신청 목록 조회"""
        try:
            apps = await self.cache_manager.get_hash_data(self._key_applications(alliance_id))
            return apps or {}
        except Exception as e:
            self.logger.error(f"Error getting applications: {e}")
            return {}
    
    async def get_application(self, alliance_id: int, user_no: int) -> Optional[Dict]:
        """특정 가입 신청 조회"""
        try:
            return await self.cache_manager.get_hash_field(
                self._key_applications(alliance_id), str(user_no)
            )
        except Exception as e:
            self.logger.error(f"Error getting application: {e}")
            return None
    
    async def add_application(self, alliance_id: int, user_no: int, app_data: Dict) -> bool:
        """가입 신청 추가"""
        try:
            return await self.cache_manager.set_hash_field(
                self._key_applications(alliance_id), str(user_no), app_data,
                expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error adding application: {e}")
            return False
    
    async def remove_application(self, alliance_id: int, user_no: int) -> bool:
        """가입 신청 제거"""
        try:
            return await self.cache_manager.delete_hash_field(
                self._key_applications(alliance_id), str(user_no)
            )
        except Exception as e:
            self.logger.error(f"Error removing application: {e}")
            return False
    
    async def delete_all_applications(self, alliance_id: int) -> bool:
        """모든 가입 신청 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_applications(alliance_id))
        except Exception as e:
            self.logger.error(f"Error deleting all applications: {e}")
            return False

    # ==================== 공지사항 ====================
    
    async def get_notice(self, alliance_id: int) -> Optional[Dict[str, Any]]:
        """공지사항 조회"""
        try:
            return await self.cache_manager.get_data(self._key_notice(alliance_id))
        except Exception as e:
            self.logger.error(f"Error getting notice: {e}")
            return None
    
    async def set_notice(self, alliance_id: int, notice_data: Dict[str, Any]) -> bool:
        """공지사항 저장"""
        try:
            return await self.cache_manager.set_data(
                self._key_notice(alliance_id), notice_data, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting notice: {e}")
            return False
    
    async def delete_notice(self, alliance_id: int) -> bool:
        """공지사항 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_notice(alliance_id))
        except Exception as e:
            self.logger.error(f"Error deleting notice: {e}")
            return False

    # ==================== 연구 진행 상태 ====================
    
    async def get_all_research(self, alliance_id: int) -> Dict[str, Dict]:
        """전체 연구 상태 조회"""
        try:
            research = await self.cache_manager.get_hash_data(self._key_research(alliance_id))
            return research or {}
        except Exception as e:
            self.logger.error(f"Error getting research: {e}")
            return {}
    
    async def get_research(self, alliance_id: int, research_idx: int) -> Optional[Dict]:
        """특정 연구 상태 조회"""
        try:
            return await self.cache_manager.get_hash_field(
                self._key_research(alliance_id), str(research_idx)
            )
        except Exception as e:
            self.logger.error(f"Error getting research {research_idx}: {e}")
            return None
    
    async def set_research(self, alliance_id: int, research_idx: int, research_data: Dict) -> bool:
        """연구 상태 저장"""
        try:
            return await self.cache_manager.set_hash_field(
                self._key_research(alliance_id), str(research_idx), research_data,
                expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting research: {e}")
            return False
    
    async def delete_all_research(self, alliance_id: int) -> bool:
        """모든 연구 상태 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_research(alliance_id))
        except Exception as e:
            self.logger.error(f"Error deleting all research: {e}")
            return False

    # ==================== 활성 연구 ====================
    
    async def get_active_research(self, alliance_id: int) -> Optional[Dict[str, Any]]:
        """현재 활성 연구 조회"""
        try:
            return await self.cache_manager.get_data(self._key_active_research(alliance_id))
        except Exception as e:
            self.logger.error(f"Error getting active research: {e}")
            return None
    
    async def set_active_research(self, alliance_id: int, data: Dict[str, Any]) -> bool:
        """활성 연구 설정"""
        try:
            return await self.cache_manager.set_data(
                self._key_active_research(alliance_id), data, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting active research: {e}")
            return False
    
    async def delete_active_research(self, alliance_id: int) -> bool:
        """활성 연구 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_active_research(alliance_id))
        except Exception as e:
            self.logger.error(f"Error deleting active research: {e}")
            return False

    # ==================== 이름 매핑 ====================
    
    async def get_alliance_id_by_name(self, name: str) -> Optional[int]:
        """이름으로 연맹 ID 조회"""
        try:
            alliance_id = await self.cache_manager.get_data(self._key_name_mapping(name))
            return int(alliance_id) if alliance_id else None
        except Exception as e:
            self.logger.error(f"Error getting alliance by name: {e}")
            return None
    
    async def set_name_mapping(self, name: str, alliance_id: int) -> bool:
        """이름 → ID 매핑 저장"""
        try:
            return await self.cache_manager.set_data(
                self._key_name_mapping(name), alliance_id, expire_time=self.cache_expire_time
            )
        except Exception as e:
            self.logger.error(f"Error setting name mapping: {e}")
            return False
    
    async def delete_name_mapping(self, name: str) -> bool:
        """이름 매핑 삭제"""
        try:
            return await self.cache_manager.delete_data(self._key_name_mapping(name))
        except Exception as e:
            self.logger.error(f"Error deleting name mapping: {e}")
            return False

    # ==================== 연맹 목록 ====================
    
    async def add_to_list(self, alliance_id: int) -> bool:
        """연맹 목록에 추가"""
        try:
            await self.redis_client.sadd(self._key_list(), alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error adding to list: {e}")
            return False
    
    async def remove_from_list(self, alliance_id: int) -> bool:
        """연맹 목록에서 제거"""
        try:
            await self.redis_client.srem(self._key_list(), alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error removing from list: {e}")
            return False
    
    async def get_all_alliance_ids(self) -> List[int]:
        """전체 연맹 ID 목록"""
        try:
            ids = await self.redis_client.smembers(self._key_list())
            return [int(id) for id in ids] if ids else []
        except Exception as e:
            self.logger.error(f"Error getting alliance list: {e}")
            return []

    # ==================== 검색 ====================
    
    async def search_alliances(self, keyword: str, limit: int = 20) -> List[Dict]:
        """연맹 검색"""
        try:
            all_ids = await self.get_all_alliance_ids()
            results = []
            
            for alliance_id in all_ids:
                info = await self.get_alliance_info(alliance_id)
                if info and keyword.lower() in info.get('name', '').lower():
                    member_count = await self.get_member_count(alliance_id)
                    results.append({**info, "member_count": member_count})
                    if len(results) >= limit:
                        break
            
            return results
        except Exception as e:
            self.logger.error(f"Error searching alliances: {e}")
            return []

    # ==================== 연맹 해산 시 전체 삭제 ====================
    
    async def delete_all_alliance_data(self, alliance_id: int, alliance_name: str) -> bool:
        """연맹 관련 모든 Redis 데이터 삭제"""
        try:
            await self.delete_all_members(alliance_id)
            await self.delete_all_applications(alliance_id)
            await self.delete_notice(alliance_id)
            await self.delete_all_research(alliance_id)
            await self.delete_active_research(alliance_id)
            await self.delete_alliance_info(alliance_id)
            await self.delete_name_mapping(alliance_name)
            await self.remove_from_list(alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting all alliance data: {e}")
            return False