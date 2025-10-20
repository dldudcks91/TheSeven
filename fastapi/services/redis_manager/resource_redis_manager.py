from datetime import datetime
from typing import Optional, Dict, Any, List
# Resource Manager는 Task를 사용하지 않으므로 BaseRedisTaskManager는 제외합니다.
from .base_redis_cache_manager import BaseRedisCacheManager 
# TaskType은 Resource Manager에 필요하지 않습니다.
import json


class ResourceRedisManager:
    """자원 전용 Redis 관리자 - Cache Manager 컴포넌트 조합 (비동기 버전)"""
    
    # 🌟 게임에서 사용하는 자원 목록을 명시적으로 정의합니다.
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    
    def __init__(self, redis_client):
        # 자원 관리는 Hash 기반 캐시 관리만 사용합니다.
        self.cache_manager = BaseRedisCacheManager(redis_client)
        self.cache_expire_time = 3600 * 24 * 7 # 7일 (자원 데이터는 반영구적일 수 있으므로 길게 설정)
        
    def _get_resources_hash_key(self, user_no: int) -> str:
        """사용자 자원 Hash 키 생성"""
        return f"user_resources:{user_no}"
    
    def _get_resources_meta_key(self, user_no: int) -> str:
        """사용자 자원 메타데이터 키 생성"""
        return f"user_resources_meta:{user_no}"
        
    def validate_resource_data(self, resource_type: str) -> bool:
        """자원 타입 유효성 검증"""
        return resource_type in self.RESOURCE_TYPES

    # === Hash 기반 캐싱 관리 메서드들 ===

    async def cache_user_resources_data(self, user_no: int, resources_data: Dict[str, Any]) -> bool:
        """Hash 구조로 자원 데이터 캐싱 (DB 로드 후 Warm-up)"""
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
            
            # Cache Manager를 통해 Hash 형태로 저장
            # resources_data는 {'resource_type': {'amount': X, ...}, ...} 형태라고 가정합니다.
            # Redis Hash Field는 resource_type, Value는 JSON 문자열이 됩니다.
            success = await self.cache_manager.set_hash_data(
                hash_key, 
                resources_data, 
                expire_time=self.cache_expire_time
            )
            
            if success:
                await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
                print(f"Successfully cached {len(resources_data)} resources for user {user_no} using Hash")
                return True
                
            return False
                
        except Exception as e:
            print(f"Error caching resources data: {e}")
            return False

    async def get_cached_resource(self, user_no: int, resource_type: str) -> Optional[Dict[str, Any]]:
        """특정 자원 하나만 캐시에서 조회"""
        if not self.validate_resource_data(resource_type):
            return None
        try:
            hash_key = self._get_resources_hash_key(user_no)
            # Hash Field는 resource_type (e.g., 'gold')입니다.
            resource_data = await self.cache_manager.get_hash_field(hash_key, resource_type)
            
            if resource_data:
                return resource_data
            
            return None
                
        except Exception as e:
            print(f"Error retrieving cached resource {resource_type} for user {user_no}: {e}")
            return None

    async def get_cached_all_resources(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 자원을 캐시에서 조회"""
        try:
            hash_key = self._get_resources_hash_key(user_no)
            resources = await self.cache_manager.get_hash_data(hash_key)
            
            if resources:
                return resources
            
            return None
                
        except Exception as e:
            print(f"Error retrieving cached resources for user {user_no}: {e}")
            return None
            
    # === 핵심 자원 증감(Atomic Operation) 메서드들 ===

    async def change_resource_amount(self, user_no: int, resource_type: str, amount_change: int) -> Optional[int]:
        """
        특정 자원의 양을 원자적으로 변경하고 변경 후 최종 잔액을 반환합니다.
        (양수: 획득, 음수: 사용/차감)
        """
        if not self.validate_resource_data(resource_type):
            print(f"Invalid resource type: {resource_type}")
            return None
        
        try:
            hash_key = self._get_resources_hash_key(user_no)
            
            # Redis Hash 내부의 필드(resource_type) 값을 원자적으로 증감 (HINCRBY 기능 위임)
            # BaseRedisCacheManager에 HINCRBY와 유사한 기능이 있다고 가정합니다.
            # 이 로직은 자원 데이터의 'amount' 필드를 JSON 객체 내부에서 직접 건드려야 하므로
            # 실제로는 Lua 스크립트를 사용하거나, amount 필드를 String 타입으로 별도 관리해야 효율적입니다.
            
            # **임시 해결책: 단일 필드에 Integer를 저장하는 별도 키 사용을 가정**
            # (Hash 필드 안에 JSON 객체가 있을 경우, HINCRBY를 직접 사용할 수 없어 캐시 전략 변경 필요)
            
            # 🌟 일반적인 Redis HASH 패턴을 따르기 위해, get_hash_field/set_hash_field를 사용하는 대신
            #    단일 String 키를 사용하도록 로직을 변경합니다. (자원 전용 키를 가정)
            
            resource_amount_key = f"user_resource_amount:{user_no}:{resource_type}"
            
            # Redis INCRBY 명령을 통해 원자적으로 증감
            new_amount = await self.cache_manager.increment_data(resource_amount_key, amount_change)

            if new_amount is not None:
                # 🌟 자원 데이터의 '최종 업데이트 시간'도 Hash에 업데이트 (옵션)
                await self.update_resource_last_dt(user_no, resource_type) 
                return new_amount
                
            return None

        except Exception as e:
            print(f"Error changing resource amount for {resource_type}: {e}")
            return None
            
    async def update_resource_last_dt(self, user_no: int, resource_type: str) -> bool:
        """특정 자원의 마지막 업데이트 시간을 Hash에 업데이트"""
        try:
            hash_key = self._get_resources_hash_key(user_no)
            update_data = {
                "last_updated": datetime.utcnow().isoformat()
            }
            
            # Hash의 특정 필드(resource_type)의 'last_updated' 필드만 업데이트 (Lua 필요)
            # Cache Manager가 JSON 필드 업데이트를 지원한다고 가정하고 호출합니다.
            # 실제로는 JSON.SET과 같은 Redis Stack 명령이 필요하며, BaseCacheManager에 해당 기능이 구현되어 있어야 합니다.
            # 현재 코드에서는 간단히 Hash 필드 전체를 덮어쓰거나, 별도의 메타 키를 사용해야 합니다.
            
            # 💡 임시 방안: Hash 필드 전체를 조회 후, 변경하고 다시 저장 (성능 저하 주의)
            current_resource = await self.cache_manager.get_hash_field(hash_key, resource_type)
            if current_resource:
                current_resource['last_updated'] = datetime.utcnow().isoformat()
                return await self.cache_manager.set_hash_field(hash_key, resource_type, current_resource, expire_time=self.cache_expire_time)
                
            return False
            
        except Exception as e:
            print(f"Error updating resource last_dt: {e}")
            return False
            
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