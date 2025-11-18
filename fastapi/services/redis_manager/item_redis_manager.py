from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType
import json


class ItemRedisManager:
    """아이템 전용 Redis 관리자 - Cache Manager 컴포넌트 사용 (비동기 버전)"""
    
    def __init__(self, redis_client):
        # Cache Manager 컴포넌트 초기화
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.ITEM)
        self.cache_expire_time = 3600  # 1시간
    
    def validate_item_data(self, item_idx: int, quantity: Optional[int] = None) -> bool:
        """아이템 데이터 유효성 검증"""
        if not isinstance(item_idx, int) or item_idx <= 0:
            return False
        if quantity is not None and (not isinstance(quantity, int) or quantity < 0):
            return False
        return True
    
    # === Hash 기반 캐싱 관리 메서드들 ===
    
    async def cache_user_items_data(self, user_no: int, items_data: Dict[str, Any]) -> bool:
        """Hash 구조로 아이템 데이터 캐싱"""
        if not items_data:
            return True
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'item_count': len(items_data),
                'user_no': user_no
            }
            
            # Cache Manager를 통해 Hash 형태로 저장
            success = await self.cache_manager.set_hash_data(
                hash_key, 
                items_data, 
                expire_time=self.cache_expire_time
            )
            
            if success:
                # 메타데이터도 저장
                await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
                print(f"Successfully cached {len(items_data)} items for user {user_no} using Hash")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error caching items data: {e}")
            return False
    
    async def get_cached_item(self, user_no: int, item_idx: int) -> Optional[Dict[str, Any]]:
        """특정 아이템 하나만 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            item_data = await self.cache_manager.get_hash_field(hash_key, str(item_idx))
            
            if item_data:
                print(f"Cache hit: Retrieved item {item_idx} for user {user_no}")
                return item_data
            
            print(f"Cache miss: Item {item_idx} not found for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached item {item_idx} for user {user_no}: {e}")
            return None
    
    async def get_cached_items(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 아이템을 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            items = await self.cache_manager.get_hash_data(hash_key)
            
            if items:
                print(f"Cache hit: Retrieved {len(items)} items for user {user_no}")
                return items
            
            print(f"Cache miss: No cached items for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached items for user {user_no}: {e}")
            return None
    
    async def update_cached_item(self, user_no: int, item_idx: int, item_data: Dict[str, Any]) -> bool:
        """특정 아이템 캐시 업데이트"""
        try:
            if not self.validate_item_data(item_idx, item_data.get('quantity')):
                return False
            
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # Cache Manager를 통해 Hash 필드 업데이트
            success = await self.cache_manager.set_hash_field(
                hash_key, 
                str(item_idx), 
                item_data,
                expire_time=self.cache_expire_time
            )
            
            if success:
                print(f"Updated cached item {item_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error updating cached item {item_idx} for user {user_no}: {e}")
            return False
    
    async def remove_cached_item(self, user_no: int, item_idx: int) -> bool:
        """특정 아이템을 캐시에서 제거"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            success = await self.cache_manager.delete_hash_field(hash_key, str(item_idx))
            
            if success:
                print(f"Removed cached item {item_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error removing cached item {item_idx} for user {user_no}: {e}")
            return False
    
    async def invalidate_item_cache(self, user_no: int) -> bool:
        """사용자 아이템 캐시 전체 무효화"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 두 키 모두 삭제
            hash_deleted = await self.cache_manager.delete_data(hash_key)
            meta_deleted = await self.cache_manager.delete_data(meta_key)
            
            success = hash_deleted or meta_deleted
            if success:
                print(f"Item cache invalidated for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error invalidating item cache for user {user_no}: {e}")
            return False
    
    async def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅/모니터링용)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # Cache Manager를 통해 정보 조회
            item_count = await self.cache_manager.get_hash_length(hash_key)
            ttl = await self.cache_manager.get_ttl(hash_key)
            meta_data = await self.cache_manager.get_data(meta_key) or {}
            
            return {
                "user_no": user_no,
                "item_count": item_count,
                "ttl_seconds": ttl,
                "meta_data": meta_data,
                "cache_exists": item_count > 0
            }
            
        except Exception as e:
            print(f"Error getting cache info for user {user_no}: {e}")
            return {"user_no": user_no, "cache_exists": False, "error": str(e)}
    
    # === 아이템 수량 관리 헬퍼 메서드들 ===
    
    async def get_item_quantity(self, user_no: int, item_idx: int) -> int:
        """특정 아이템 수량 조회"""
        try:
            item_data = await self.get_cached_item(user_no, item_idx)
            
            if item_data:
                return item_data.get('quantity', 0)
            
            return 0
            
        except Exception as e:
            print(f"Error getting item quantity: {e}")
            return 0
    
    async def update_item_quantity(self, user_no: int, item_idx: int, new_quantity: int) -> bool:
        """아이템 수량 업데이트"""
        try:
            if not self.validate_item_data(item_idx, new_quantity):
                return False
            
            item_data = {
                "user_no": user_no,
                "item_idx": item_idx,
                "quantity": new_quantity,
                "cached_at": datetime.utcnow().isoformat()
            }
            
            # 수량이 0 이하면 캐시에서 제거
            if new_quantity <= 0:
                return await self.remove_cached_item(user_no, item_idx)
            
            return await self.update_cached_item(user_no, item_idx, item_data)
            
        except Exception as e:
            print(f"Error updating item quantity: {e}")
            return False
    
    # === 컴포넌트 접근 메서드들 (필요시 직접 접근) ===
    
    def get_cache_manager(self) -> BaseRedisCacheManager:
        """Cache Manager 컴포넌트 반환"""
        return self.cache_manager
    
    # === 통합 유틸리티 메서드들 ===
    
    async def get_item_status(self, user_no: int, item_idx: int) -> Dict[str, Any]:
        """아이템의 전체 상태 조회 (캐시 정보)"""
        try:
            # 캐시에서 정보 조회
            cached_item = await self.get_cached_item(user_no, item_idx)
            
            status = {
                "item_idx": item_idx,
                "user_no": user_no,
                "cached_data": cached_item,
                "quantity": cached_item.get('quantity', 0) if cached_item else 0,
                "in_cache": cached_item is not None,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return status
            
        except Exception as e:
            print(f"Error getting item status for {item_idx}: {e}")
            return {
                "item_idx": item_idx,
                "user_no": user_no,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }