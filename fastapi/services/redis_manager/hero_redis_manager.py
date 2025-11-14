# hero_redis_manager.py

from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType, TaskType # CacheType.HERO, TaskType.HERO_UPGRADE가 필요하다고 가정
import json


class HeroRedisManager:
    """영웅 전용 Redis 관리자 - Task Manager와 Cache Manager 컴포넌트 조합 (비동기 버전)"""
    
    def __init__(self, redis_client):
        # 두 개의 매니저 컴포넌트 초기화
        # 영웅 레벨업 등 작업은 TaskType.HERO_UPGRADE 사용을 가정
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.HERO_UPGRADE)
        # 영웅 데이터 캐싱은 CacheType.HERO 사용을 가정
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.HERO)
        self.redis_client = redis_client # 직접 접근용
        
        self.cache_expire_time = 3600  # 1시간
    
    def validate_task_data(self, hero_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """영웅 작업 데이터 유효성 검증"""
        return isinstance(hero_idx, int) and hero_idx > 0
    
    # === Task Manager 위임 메서드들 (예시: 영웅 레벨업 큐) ===
    async def add_hero_upgrade_to_queue(self, user_no: int, hero_idx: int, completion_time: datetime) -> bool:
        """영웅 레벨업 작업을 완료 큐에 추가"""
        if not self.validate_task_data(hero_idx):
            return False
        # hero_idx를 task_id로 사용하고, completion_time을 스코어(ZSET)로 사용
        return await self.task_manager.add_to_queue(user_no, str(hero_idx), completion_time)

    async def get_hero_upgrade_completion_time(self, user_no: int, hero_idx: int) -> Optional[datetime]:
        """특정 영웅의 레벨업 완료 시간 조회"""
        return await self.task_manager.get_completion_time(user_no, str(hero_idx))
    
    # === Cache Manager 위임 메서드들 (영웅 데이터 캐싱) ===
    async def get_cached_heroes(self, user_no: int) -> Dict[str, Any]:
        """사용자의 모든 영웅 데이터를 캐시에서 조회"""
        return await self.cache_manager.get_all_cached_data(user_no)

    async def get_cached_hero(self, user_no: int, hero_idx: int) -> Optional[Dict[str, Any]]:
        """특정 영웅 데이터를 캐시에서 조회"""
        return await self.cache_manager.get_cached_data(user_no, str(hero_idx))

    async def update_cached_hero(self, user_no: int, hero_idx: int, hero_data: Dict[str, Any]):
        """특정 영웅 데이터를 캐시에 업데이트/저장"""
        # 영웅 데이터는 JSON 문자열로 저장
        await self.cache_manager.set_cached_data(user_no, str(hero_idx), json.dumps(hero_data), self.cache_expire_time)

    async def remove_cached_hero(self, user_no: int, hero_idx: int):
        """특정 영웅 데이터를 캐시에서 삭제 (예: 영웅 해고 시)"""
        await self.cache_manager.remove_cached_data(user_no, str(hero_idx))
    
    # === 통합 유틸리티 메서드들 (필요시 추가) ===
    # 예: get_hero_status 등