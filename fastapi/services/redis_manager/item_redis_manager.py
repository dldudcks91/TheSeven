# item_redis_manager.py

from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType, TaskType # CacheType.ITEM, TaskType.ITEM_USAGE가 필요하다고 가정
import json


class ItemRedisManager:
    """아이템 전용 Redis 관리자 - Task Manager와 Cache Manager 컴포넌트 조합 (비동기 버전)"""
    
    def __init__(self, redis_client):
        # 두 개의 매니저 컴포넌트 초기화
        # 아이템 사용 등 작업은 TaskType.ITEM_USAGE 사용을 가정 (UnitManager와 달리 아이템은 큐가 필요 없을 수도 있으나, 확장성을 위해 포함)
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.ITEM_USAGE)
        # 인벤토리 데이터 캐싱은 CacheType.ITEM 사용을 가정
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.ITEM)
        self.redis_client = redis_client # 직접 접근용
        
        self.cache_expire_time = 3600  # 1시간
    
    def validate_task_data(self, item_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """아이템 작업 데이터 유효성 검증"""
        if not isinstance(item_idx, int) or item_idx <= 0:
            return False
        # 수량 체크 등은 비즈니스 로직에 따라 추가
        return True
    
    # === Task Manager 위임 메서드들 (예시: 아이템 사용 큐) ===
    async def add_item_usage_to_queue(self, user_no: int, task_id: str, completion_time: datetime) -> bool:
        """아이템 사용 작업을 완료 큐에 추가"""
        # task_id는 item_idx와 기타 정보의 조합일 수 있음 (예: f"{item_idx}:{user_no}:{timestamp}")
        return await self.task_manager.add_to_queue(user_no, task_id, completion_time)

    async def get_item_usage_completion_time(self, user_no: int, task_id: str) -> Optional[datetime]:
        """특정 아이템 사용 작업의 완료 시간 조회"""
        return await self.task_manager.get_completion_time(user_no, task_id)
    
    # === Cache Manager 위임 메서드들 (인벤토리 데이터 캐싱) ===
    async def get_cached_inventory(self, user_no: int) -> Dict[str, Any]:
        """사용자의 모든 인벤토리 데이터를 캐시에서 조회"""
        # {item_idx: item_data} 형태로 반환
        return await self.cache_manager.get_all_cached_data(user_no)

    async def get_cached_item(self, user_no: int, item_idx: int) -> Optional[Dict[str, Any]]:
        """특정 아이템 데이터를 캐시에서 조회 (수량 포함)"""
        return await self.cache_manager.get_cached_data(user_no, str(item_idx))

    async def update_cached_item(self, user_no: int, item_idx: int, item_data: Dict[str, Any]):
        """특정 아이템 데이터를 캐시에 업데이트/저장"""
        await self.cache_manager.set_cached_data(user_no, str(item_idx), json.dumps(item_data), self.cache_expire_time)

    async def increment_item_quantity(self, user_no: int, item_idx: int, amount: int = 1):
        """특정 아이템의 수량 필드를 증가 (HINCRBY 사용)"""
        # cache_manager에 HASH 구조로 직접 접근하는 메서드가 필요할 수 있음
        await self.cache_manager.increment_field(user_no, str(item_idx), 'quantity', amount)
        
    async def decrement_item_quantity(self, user_no: int, item_idx: int, amount: int = 1):
        """특정 아이템의 수량 필드를 감소"""
        await self.cache_manager.decrement_field(user_no, str(item_idx), 'quantity', amount)
        
    # === 통합 유틸리티 메서드들 (필요시 추가) ===