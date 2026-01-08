from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType, TaskType
import logging


class BuffRedisManager:
    """
    버프 전용 Redis 관리자
    
    저장 구조:
        permanent_buffs (Hash) - target_type별 분류:
            Field: "unit"     → {"research:101_3": {"buff_idx": 202, "stat_type": "attack", ...}, ...}
            Field: "resource" → {"research:201_1": {"buff_idx": 101, "stat_type": "get", ...}, ...}
            Field: "building" → {...}
        
        temporary_buffs:
            TaskManager(만료 큐) + 개별 메타데이터 (String)
        
        total_buffs (String) - 캐시:
            {"unit:attack:infantry": 15.0, "resource:get:all": 10.0, ...}
    """
    
    def __init__(self, redis_client):
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.BUFF)
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.BUFF)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.cache_expire_time = 3600  # 영구버프 캐시 1시간
        self.total_buffs_ttl = 60      # total_buffs 캐시 60초

    # ==================== 영구 버프 ====================

    async def get_permanent_buffs(self, user_no: int) -> Optional[Dict[str, Dict]]:
        """
        영구 버프 전체 조회
        
        Returns:
            None if cache miss
            {
                "unit": {"research:101_3": {"buff_idx": 202, ...}, ...},
                "resource": {"research:201_1": {"buff_idx": 101, ...}, ...}
            }
        """
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            buffs = await self.cache_manager.get_hash_data(hash_key)
            
            if buffs:
                self.logger.debug(f"Cache hit: permanent buffs for user {user_no}")
                return buffs
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting permanent buffs: {e}")
            return None

    async def get_permanent_buffs_by_type(self, user_no: int, target_type: str) -> Optional[Dict]:
        """
        특정 target_type의 영구 버프만 조회
        
        Args:
            target_type: "unit", "resource", "building" 등
            
        Returns:
            {"research:101_3": {"buff_idx": 202, ...}, ...}
        """
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            buffs = await self.cache_manager.get_hash_field(hash_key, target_type)
            
            if buffs:
                self.logger.debug(f"Cache hit: {target_type} buffs for user {user_no}")
                return buffs
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting {target_type} buffs: {e}")
            return None

    async def cache_permanent_buffs(self, user_no: int, buffs: Dict[str, Dict]) -> bool:
        """
        영구 버프 전체 캐싱
        
        Args:
            buffs: {
                "unit": {"research:101_3": {...}, ...},
                "resource": {"research:201_1": {...}, ...}
            }
        """
        if not buffs:
            return True
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            success = await self.cache_manager.set_hash_data(
                hash_key, buffs, expire_time=self.cache_expire_time
            )
            
            if success:
                self.logger.info(f"Cached permanent buffs for user {user_no}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error caching permanent buffs: {e}")
            return False

    async def set_permanent_buff(self, user_no: int, target_type: str,
                                  source_key: str, buff_data: Dict) -> bool:
        """
        단일 영구 버프 추가/업데이트
        
        Args:
            target_type: "unit", "resource", "building" 등
            source_key: "research:101_3", "title:5" 등
            buff_data: {
                "buff_idx": 202,
                "target_type": "unit",
                "target_sub_type": "infantry",
                "stat_type": "attack",
                "value": 5,
                "value_type": "percentage"
            }
        """
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # 해당 target_type의 기존 데이터 조회
            existing = await self.cache_manager.get_hash_field(hash_key, target_type)
            if existing is None:
                existing = {}
            
            # 새 버프 추가
            existing[source_key] = buff_data
            
            # 저장
            success = await self.cache_manager.set_hash_field(
                hash_key, target_type, existing, expire_time=self.cache_expire_time
            )
            
            if success:
                self.logger.debug(f"Set permanent buff {target_type}:{source_key} for user {user_no}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error setting permanent buff: {e}")
            return False

    async def del_permanent_buff(self, user_no: int, target_type: str, source_key: str) -> bool:
        """단일 영구 버프 삭제"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            existing = await self.cache_manager.get_hash_field(hash_key, target_type)
            if existing and source_key in existing:
                del existing[source_key]
                
                if existing:
                    await self.cache_manager.set_hash_field(
                        hash_key, target_type, existing, expire_time=self.cache_expire_time
                    )
                else:
                    await self.cache_manager.delete_hash_field(hash_key, target_type)
                
                self.logger.debug(f"Deleted permanent buff {target_type}:{source_key} for user {user_no}")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error deleting permanent buff: {e}")
            return False

    async def invalidate_permanent_buffs(self, user_no: int) -> bool:
        """영구 버프 캐시 전체 무효화"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            return await self.cache_manager.delete_data(hash_key)
        except Exception as e:
            self.logger.error(f"Error invalidating permanent buffs: {e}")
            return False

    # ==================== 임시 버프 ====================

    def _get_temp_buff_key(self, user_no: int, buff_id: str) -> str:
        return f"user:{user_no}:temp_buff:{buff_id}"

    async def add_temp_buff(self, user_no: int, buff_id: str,
                            metadata: Dict, duration: int) -> bool:
        """
        임시 버프 추가
        
        Args:
            metadata: {
                "buff_idx": 201,
                "target_type": "unit",
                "target_sub_type": "all",
                "stat_type": "speed",
                "value": 10,
                "value_type": "percentage",
                "expires_at": "2025-01-08T12:00:00Z",
                "source": "item"
            }
        """
        try:
            meta_key = self._get_temp_buff_key(user_no, buff_id)
            
            # 메타데이터 저장
            await self.cache_manager.set_data(meta_key, metadata, expire_time=duration)
            
            # 만료 큐 등록
            completion_time = datetime.utcnow() + timedelta(seconds=duration)
            success = await self.task_manager.add_to_queue(user_no, buff_id, completion_time)
            
            if success:
                self.logger.debug(f"Added temp buff {buff_id} for user {user_no}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error adding temp buff: {e}")
            return False

    async def get_temp_buffs(self, user_no: int) -> List[Dict]:
        """
        활성 임시 버프 목록 조회
        
        Returns:
            [
                {
                    "buff_id": "abc123",
                    "buff_idx": 201,
                    "target_type": "unit",
                    "target_sub_type": "all",
                    "stat_type": "speed",
                    "value": 10,
                    "value_type": "percentage",
                    "expires_at": "2025-01-08T12:00:00Z",
                    "source": "item"
                },
                ...
            ]
        """
        try:
            active_tasks = await self.task_manager.get_user_tasks(user_no)
            
            results = []
            for task in active_tasks:
                buff_id = task['task_id']
                meta_key = self._get_temp_buff_key(user_no, buff_id)
                
                meta = await self.cache_manager.get_data(meta_key)
                if meta:
                    meta['buff_id'] = buff_id
                    results.append(meta)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error getting temp buffs: {e}")
            return []

    async def get_temp_buffs_by_type(self, user_no: int, target_type: str) -> List[Dict]:
        """특정 target_type의 임시 버프만 조회"""
        all_buffs = await self.get_temp_buffs(user_no)
        return [b for b in all_buffs if b.get('target_type') == target_type]

    async def remove_temp_buff(self, user_no: int, buff_id: str) -> bool:
        """임시 버프 제거"""
        try:
            meta_key = self._get_temp_buff_key(user_no, buff_id)
            
            await self.cache_manager.delete_data(meta_key)
            await self.task_manager.remove_from_queue(user_no, buff_id)
            
            self.logger.debug(f"Removed temp buff {buff_id} for user {user_no}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error removing temp buff: {e}")
            return False

    async def get_expired_temp_buffs(self, current_time: Optional[datetime] = None) -> List[Dict]:
        """만료된 임시 버프 조회 (배치 처리용)"""
        return await self.task_manager.get_completed_tasks(current_time)

    # ==================== Total Buffs 캐시 ====================

    def _get_total_buffs_key(self, user_no: int) -> str:
        return f"user:{user_no}:total_buffs"

    async def get_total_buffs_cache(self, user_no: int) -> Optional[Dict[str, float]]:
        """
        total_buffs 캐시 조회
        
        Returns:
            None if cache miss
            {"unit:attack:infantry": 15.0, "resource:get:all": 10.0, ...}
        """
        try:
            cache_key = self._get_total_buffs_key(user_no)
            return await self.cache_manager.get_data(cache_key)
        except Exception as e:
            self.logger.error(f"Error getting total buffs cache: {e}")
            return None

    async def set_total_buffs_cache(self, user_no: int, totals: Dict[str, float]) -> bool:
        """total_buffs 캐시 저장 (TTL 60초)"""
        try:
            cache_key = self._get_total_buffs_key(user_no)
            return await self.cache_manager.set_data(
                cache_key, totals, expire_time=self.total_buffs_ttl
            )
        except Exception as e:
            self.logger.error(f"Error setting total buffs cache: {e}")
            return False

    async def invalidate_total_buffs_cache(self, user_no: int) -> bool:
        """total_buffs 캐시 무효화 (버프 변경 시 호출)"""
        try:
            cache_key = self._get_total_buffs_key(user_no)
            await self.cache_manager.delete_data(cache_key)
            self.logger.debug(f"Invalidated total_buffs cache for user {user_no}")
            return True
        except Exception as e:
            self.logger.error(f"Error invalidating total buffs cache: {e}")
            return False

    # ==================== 유틸리티 ====================

    async def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅용)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            permanent = await self.get_permanent_buffs(user_no) or {}
            temp_buffs = await self.get_temp_buffs(user_no)
            total_buffs = await self.get_total_buffs_cache(user_no)
            ttl = await self.cache_manager.get_ttl(hash_key)
            
            # 각 target_type별 버프 수
            permanent_counts = {k: len(v) for k, v in permanent.items()}
            
            return {
                "user_no": user_no,
                "permanent_buffs_by_type": permanent_counts,
                "temp_buff_count": len(temp_buffs),
                "total_buffs_cached": total_buffs is not None,
                "ttl_seconds": ttl,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting cache info: {e}")
            return {"user_no": user_no, "error": str(e)}