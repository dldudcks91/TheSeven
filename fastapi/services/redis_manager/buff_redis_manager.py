from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType, TaskType
import json

class BuffRedisManager:
    """
    버프 전용 Redis 관리자 (데이터 접근 계층)
    - BuildingRedisManager와 동일한 구조로 Task(임시)와 Cache(영구/계산)를 관리
    - 비즈니스 로직 없음 (Manager가 제어)
    """
    
    def __init__(self, redis_client):
        # 1. 임시 버프(시간제) 관리를 위한 TaskManager
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.BUFF)
        # 2. 영구 버프 및 계산 결과 관리를 위한 CacheManager
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.BUFF)
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간

    # ==================== 영구 버프 (Permanent Buffs) ====================
    # Hash 구조: user:{user_no}:permanent_buffs

    async def get_permanent_buffs(self, user_no: int) -> Optional[Dict[str, str]]:
        """
        영구 버프 조회
        Returns: None if cache miss, Dict if exists
        """
        key = f"user:{user_no}:permanent_buffs"
        buffs = await self.redis_client.hgetall(key)
        
        if not buffs:
            return None
            
        # bytes -> str 변환
        return {k.decode() if isinstance(k, bytes) else k: 
                v.decode() if isinstance(v, bytes) else v 
                for k, v in buffs.items()}

    async def cache_permanent_buffs(self, user_no: int, buffs_mapping: Dict[str, str]) -> bool:
        """
        영구 버프 일괄 캐싱 (Manager가 복구한 데이터를 저장할 때 사용)
        """
        if not buffs_mapping:
            return True
        key = f"user:{user_no}:permanent_buffs"
        try:
            # 기존 키 덮어쓰기 (HSET)
            return await self.redis_client.hset(key, mapping=buffs_mapping)
        except Exception as e:
            print(f"Error caching permanent buffs: {e}")
            return False

    async def set_permanent_buff(self, user_no: int, field: str, buff_idx: int) -> bool:
        """단일 영구 버프 추가/업데이트"""
        key = f"user:{user_no}:permanent_buffs"
        return await self.redis_client.hset(key, field, str(buff_idx))

    async def del_permanent_buff(self, user_no: int, field: str) -> bool:
        """단일 영구 버프 삭제"""
        key = f"user:{user_no}:permanent_buffs"
        return await self.redis_client.hdel(key, field)

    # ==================== 임시 버프 (Temporary Buffs) ====================
    # Task Queue + Metadata Cache 구조

    async def add_temp_buff_task(self, user_no: int, buff_id: str, metadata: Dict[str, Any], duration: int) -> bool:
        """임시 버프 메타데이터 캐싱 및 만료 큐 등록"""
        meta_key = f"user:{user_no}:temp_buff:{buff_id}"
        
        # 1. 메타데이터 저장 (CacheManager 활용)
        await self.cache_manager.set_data(meta_key, metadata, expire_time=duration)
        
        # 2. 완료 큐에 등록 (TaskManager 활용)
        completion_time = datetime.utcnow() + timedelta(seconds=duration)
        return await self.task_manager.add_to_queue(user_no, buff_id, completion_time)

    async def get_active_temp_buffs(self, user_no: int) -> List[Dict[str, Any]]:
        """활성화된 임시 버프 목록 조회"""
        # TaskManager를 통해 현재 유효한 작업 목록 조회
        active_tasks = await self.task_manager.get_user_tasks(user_no)
        
        results = []
        for task in active_tasks:
            buff_id = task['task_id']
            meta_key = f"user:{user_no}:temp_buff:{buff_id}"
            
            # 메타데이터 조회
            meta = await self.cache_manager.get_data(meta_key)
            if meta:
                meta['buff_id'] = buff_id
                results.append(meta)
        return results

    async def remove_temp_buff(self, user_no: int, buff_id: str) -> bool:
        """임시 버프 제거"""
        meta_key = f"user:{user_no}:temp_buff:{buff_id}"
        await self.cache_manager.delete_data(meta_key)
        return await self.task_manager.remove_from_queue(user_no, buff_id)

    # ==================== 계산 결과 캐시 (Calculation Cache) ====================
    
    async def get_total_buff_cache(self, cache_key: str) -> Optional[float]:
        """계산된 총합 버프 조회"""
        val = await self.redis_client.get(cache_key)
        if val is not None:
            return float(val.decode() if isinstance(val, bytes) else val)
        return None

    async def set_total_buff_cache(self, cache_key: str, value: float, ttl: int):
        """계산된 총합 버프 저장"""
        return await self.redis_client.setex(cache_key, ttl, str(value))

    async def invalidate_buff_calculation_cache(self, user_no: int):
        """유저의 버프 계산 캐시 전체 삭제"""
        pattern = f"user:{user_no}:buff_cache:*"
        return await self.cache_manager.delete_by_pattern(pattern)