from datetime import datetime
from typing import Optional, Dict, Any, List
from .base_redis_cache_manager import BaseRedisCacheManager 
import json
from .redis_types import CacheType


class ResourceRedisManager:
    """자원 전용 Redis 관리자 - Hash 구조 사용 (비동기 버전)"""
    
    # 게임에서 사용하는 자원 목록
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    
    def __init__(self, redis_client):
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.RESOURCES)
        self.cache_expire_time = 3600 * 24 * 7  # 7일
        
    def _get_resources_hash_key(self, user_no: int) -> str:
        """사용자 자원 Hash 키 생성 - user_resources:1"""
        return f"user_resources:{user_no}"
    
    def _get_resources_meta_key(self, user_no: int) -> str:
        """사용자 자원 메타데이터 키 생성"""
        return f"user_resources_meta:{user_no}"
        
    def validate_resource_data(self, resource_type: str) -> bool:
        """자원 타입 유효성 검증"""
        return resource_type in self.RESOURCE_TYPES

    # === Hash 기반 캐싱 관리 메서드들 ===

    async def cache_user_resources_data(self, user_no: int, resources_data: Dict[str, int]) -> bool:
        """
        Hash 구조로 자원 데이터 캐싱 (DB 로드 후 Warm-up)
        
        Args:
            resources_data: {'food': 1000, 'wood': 500, 'stone': 300}
            
        Redis 구조:
            HSET user_resources:1 food 1000 wood 500 stone 300
        """
        if not resources_data:
            return True
        
        try:
            hash_key = self._get_resources_hash_key(user_no)
            meta_key = self._get_resources_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'resource_count': len(resources_data),
                'user_no': user_no
            }
            
            # Hash에 자원 정수값 직접 저장 (JSON 직렬화 없이)
            # BaseRedisCacheManager.set_hash_data는 JSON 직렬화하므로
            # 직접 Redis 명령 사용
            pipeline = self.cache_manager.redis_client.pipeline()
            
            for resource_type, amount in resources_data.items():
                if resource_type in self.RESOURCE_TYPES:
                    pipeline.hset(hash_key, resource_type, int(amount))
            
            pipeline.expire(hash_key, self.cache_expire_time)
            await pipeline.execute()
            
            # 메타데이터 저장
            await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
            
            print(f"Successfully cached {len(resources_data)} resources for user {user_no} using Hash")
            return True
                
        except Exception as e:
            print(f"Error caching resources data: {e}")
            return False

    async def get_cached_resource(self, user_no: int, resource_type: str) -> Optional[int]:
        """
        특정 자원 하나만 캐시에서 조회
        
        Returns:
            자원 양(int), 없으면 None
        """
        if not self.validate_resource_data(resource_type):
            return None
        try:
            hash_key = self._get_resources_hash_key(user_no)
            value = await self.cache_manager.redis_client.hget(hash_key, resource_type)
            
            if value:
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                return int(value)
            
            return None
                
        except Exception as e:
            print(f"Error retrieving cached resource {resource_type} for user {user_no}: {e}")
            return None

    async def get_cached_all_resources(self, user_no: int) -> Optional[Dict[str, int]]:
        """
        모든 자원을 캐시에서 조회
        
        Returns:
            {'food': 1000, 'wood': 500, ...}
        """
        try:
            hash_key = self._get_resources_hash_key(user_no)
            resources_raw = await self.cache_manager.redis_client.hgetall(hash_key)
            
            if resources_raw:
                # bytes를 int로 변환
                resources = {}
                for field, value in resources_raw.items():
                    if isinstance(field, bytes):
                        field = field.decode('utf-8')
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    
                    if field in self.RESOURCE_TYPES:
                        resources[field] = int(value)
                
                return resources
            
            return None
                
        except Exception as e:
            print(f"Error retrieving cached resources for user {user_no}: {e}")
            return None
            
    # === 핵심 자원 증감 메서드 ===

    async def change_resource_amount(self, user_no: int, resource_type: str, amount_change: int) -> Optional[int]:
        """
        특정 자원의 양을 원자적으로 변경
        
        Args:
            user_no: 사용자 번호
            resource_type: 자원 타입 (food, wood, stone, gold, ruby)
            amount_change: 증감량 (양수: 획득, 음수: 소모)
            
        Returns:
            변경 후 자원 양, 실패 시 None
            
        Redis 구조:
            HINCRBY user_resources:1 food -800
        """
        if not self.validate_resource_data(resource_type):
            print(f"Invalid resource type: {resource_type}")
            return None
        
        try:
            hash_key = self._get_resources_hash_key(user_no)
            
            # Redis HINCRBY 명령으로 Hash 필드를 원자적으로 증감
            new_amount = await self.cache_manager.increment_hash_field(hash_key, resource_type, amount_change)

            if new_amount is not None:
                # 음수 체크: 자원이 부족한 경우 롤백
                if new_amount < 0:
                    # 변경 사항 롤백 (원래대로 되돌림)
                    await self.cache_manager.increment_hash_field(hash_key, resource_type, -amount_change)
                    print(f"Insufficient resource {resource_type} for user {user_no}. "
                          f"Attempted: {amount_change}, Result would be: {new_amount}. Rolled back.")
                    return None
                
                # 성공 시 반환
                return new_amount
                
            return None

        except Exception as e:
            print(f"Error changing resource amount for {resource_type}: {e}")
            return None
            
    # === 캐시 무효화 및 디버깅 메서드 ===
    
    async def invalidate_resource_cache(self, user_no: int) -> bool:
        """사용자 자원 캐시 전체 무효화"""
        try:
            hash_key = self._get_resources_hash_key(user_no)
            meta_key = self._get_resources_meta_key(user_no)
            
            hash_deleted = await self.cache_manager.delete_data(hash_key)
            meta_deleted = await self.cache_manager.delete_data(meta_key)
            
            success = hash_deleted or meta_deleted
            return success
                
        except Exception as e:
            print(f"Error invalidating resource cache for user {user_no}: {e}")
            return False