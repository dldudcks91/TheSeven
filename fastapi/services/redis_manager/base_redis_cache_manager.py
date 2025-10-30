from datetime import datetime
from typing import Optional, Dict, Any, List, Union
import json
import logging


class BaseRedisCacheManager:
    """Redis 캐시 관리 기본 클래스 - Hash 및 일반 캐싱 지원 (비동기 버전)"""
    
    def __init__(self, redis_client, default_expire_time: int = 3600):
        """
        Args:
            redis_client: Redis 클라이언트 인스턴스
            default_expire_time: 기본 만료 시간 (초, 기본값: 1시간)
        """
        self.redis_client = redis_client
        self.default_expire_time = default_expire_time
        self.logger = logging.getLogger(self.__class__.__name__)
    
    # === 일반 캐싱 메서드들 ===
    
    async def set_data(self, key: str, data: Any, expire_time: Optional[int] = None) -> bool:
        """일반 데이터 캐싱"""
        try:
            expire_time = expire_time or self.default_expire_time
            
            # 데이터를 JSON으로 직렬화
            serialized_data = json.dumps(data, default=str)
            
            # Redis에 저장
            result = await self.redis_client.setex(key, expire_time, serialized_data)
            
            self.logger.debug(f"Cached data with key: {key}, expire: {expire_time}s")
            return result
            
        except Exception as e:
            self.logger.error(f"Error setting cache data for key {key}: {e}")
            return False
    
    async def get_data(self, key: str) -> Optional[Any]:
        """일반 데이터 조회"""
        try:
            cached_data = await self.redis_client.get(key)
            
            if cached_data:
                # bytes를 string으로 변환 후 JSON 파싱
                if isinstance(cached_data, bytes):
                    cached_data = cached_data.decode('utf-8')
                
                data = json.loads(cached_data)
                self.logger.debug(f"Cache hit for key: {key}")
                return data
            
            self.logger.debug(f"Cache miss for key: {key}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting cache data for key {key}: {e}")
            return None
    
    async def delete_data(self, key: str) -> bool:
        """데이터 삭제"""
        try:
            result = await self.redis_client.delete(key)
            
            if result > 0:
                self.logger.debug(f"Deleted cache data for key: {key}")
            
            return result > 0
            
        except Exception as e:
            self.logger.error(f"Error deleting cache data for key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """키 존재 여부 확인"""
        try:
            return bool(await self.redis_client.exists(key))
        except Exception as e:
            self.logger.error(f"Error checking existence of key {key}: {e}")
            return False
    
    async def get_ttl(self, key: str) -> int:
        """키의 TTL 조회"""
        try:
            return await self.redis_client.ttl(key)
        except Exception as e:
            self.logger.error(f"Error getting TTL for key {key}: {e}")
            return -1
    
    async def extend_ttl(self, key: str, expire_time: Optional[int] = None) -> bool:
        """TTL 연장"""
        try:
            expire_time = expire_time or self.default_expire_time
            result = await self.redis_client.expire(key, expire_time)
            
            if result:
                self.logger.debug(f"Extended TTL for key {key} to {expire_time}s")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extending TTL for key {key}: {e}")
            return False
    
    # === 원자적 증감 메서드들 ===
    
    async def increment_data(self, key: str, amount: int = 1) -> Optional[int]:
        """
        정수 값을 원자적으로 증감합니다 (Redis INCRBY).
        
        이 메서드는 ResourceRedisManager의 change_resource_amount에서 사용됩니다.
        
        Args:
            key: Redis 키 (예: "user_resource_amount:1:food")
            amount: 증감량 (양수: 증가, 음수: 감소)
            
        Returns:
            변경 후 값, 실패 시 None
            
        Example:
            # 자원 800 소모
            new_amount = await manager.increment_data("user_resource_amount:1:food", -800)
            
            # 자원 500 획득
            new_amount = await manager.increment_data("user_resource_amount:1:wood", 500)
        """
        try:
            new_value = await self.redis_client.incrby(key, amount)
            self.logger.debug(f"Incremented key {key} by {amount}, new value: {new_value}")
            return new_value
            
        except Exception as e:
            self.logger.error(f"Error incrementing key {key}: {e}")
            return None
    
    async def decrement_data(self, key: str, amount: int = 1) -> Optional[int]:
        """
        정수 값을 원자적으로 감소합니다 (Redis DECRBY).
        
        Args:
            key: Redis 키
            amount: 감소량 (양수)
            
        Returns:
            변경 후 값, 실패 시 None
        """
        try:
            new_value = await self.redis_client.decrby(key, amount)
            self.logger.debug(f"Decremented key {key} by {amount}, new value: {new_value}")
            return new_value
            
        except Exception as e:
            self.logger.error(f"Error decrementing key {key}: {e}")
            return None
    
    async def increment_hash_field(self, hash_key: str, field: str, amount: int = 1) -> Optional[int]:
        """
        Hash 필드의 정수 값을 원자적으로 증감합니다 (Redis HINCRBY).
        
        Args:
            hash_key: Redis Hash 키
            field: Hash 필드명
            amount: 증감량 (양수: 증가, 음수: 감소)
            
        Returns:
            변경 후 값, 실패 시 None
            
        Example:
            # Hash 구조에서 food 필드를 800 감소
            new_value = await manager.increment_hash_field(
                "user:1:resources", "food", -800
            )
        """
        try:
            new_value = await self.redis_client.hincrby(hash_key, str(field), amount)
            self.logger.debug(f"Incremented field {field} in hash {hash_key} by {amount}, new value: {new_value}")
            return new_value
            
        except Exception as e:
            self.logger.error(f"Error incrementing hash field {field} in {hash_key}: {e}")
            return None
    
    # === Hash 캐싱 메서드들 ===
    
    async def set_hash_data(self, hash_key: str, data: Dict[str, Any], 
                      expire_time: Optional[int] = None) -> bool:
        """Hash 구조로 데이터 전체 저장"""
        try:
            if not data:
                return True
            
            expire_time = expire_time or self.default_expire_time
            
            # 기존 Hash 삭제 후 새로 저장
            pipeline = self.redis_client.pipeline()
            pipeline.delete(hash_key)
            
            # 각 필드를 JSON으로 직렬화하여 저장
            hash_data = {}
            for field, value in data.items():
                hash_data[str(field)] = json.dumps(value, default=str)
            
            pipeline.hmset(hash_key, hash_data)
            pipeline.expire(hash_key, expire_time)
            
            results = await pipeline.execute()
            
            self.logger.debug(f"Cached {len(data)} fields in hash: {hash_key}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting hash data for {hash_key}: {e}")
            return False
    
    async def get_hash_data(self, hash_key: str) -> Optional[Dict[str, Any]]:
        """Hash 구조 데이터 전체 조회"""
        try:
            cached_data = await self.redis_client.hgetall(hash_key)
            
            if cached_data:
                result = {}
                for field, value in cached_data.items():
                    # bytes를 string으로 변환
                    if isinstance(field, bytes):
                        field = field.decode('utf-8')
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    
                    # JSON 파싱
                    result[field] = json.loads(value)
                
                self.logger.debug(f"Cache hit: Retrieved {len(result)} fields from hash {hash_key}")
                return result
            
            self.logger.debug(f"Cache miss: No data in hash {hash_key}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting hash data for {hash_key}: {e}")
            return None
    
    async def set_hash_field(self, hash_key: str, field: str, value: Any, 
                       expire_time: Optional[int] = None) -> bool:
        """Hash의 특정 필드 설정"""
        try:
            expire_time = expire_time or self.default_expire_time
            
            # 값을 JSON으로 직렬화
            serialized_value = json.dumps(value, default=str)
            
            pipeline = self.redis_client.pipeline()
            pipeline.hset(hash_key, str(field), serialized_value)
            pipeline.expire(hash_key, expire_time)  # TTL 갱신
            
            results = await pipeline.execute()
            
            self.logger.debug(f"Set hash field {field} in {hash_key}")
            return bool(results[0])
            
        except Exception as e:
            self.logger.error(f"Error setting hash field {field} in {hash_key}: {e}")
            return False
    
    async def get_hash_field(self, hash_key: str, field: str) -> Optional[Any]:
        """Hash의 특정 필드 조회"""
        try:
            value = await self.redis_client.hget(hash_key, str(field))
            
            if value:
                # bytes를 string으로 변환 후 JSON 파싱
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                
                data = json.loads(value)
                self.logger.debug(f"Cache hit: Retrieved field {field} from hash {hash_key}")
                return data
            
            self.logger.debug(f"Cache miss: Field {field} not found in hash {hash_key}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting hash field {field} from {hash_key}: {e}")
            return None
    
    async def delete_hash_field(self, hash_key: str, field: str) -> bool:
        """Hash의 특정 필드 삭제"""
        try:
            result = await self.redis_client.hdel(hash_key, str(field))
            
            if result > 0:
                self.logger.debug(f"Deleted field {field} from hash {hash_key}")
            
            return result > 0
            
        except Exception as e:
            self.logger.error(f"Error deleting hash field {field} from {hash_key}: {e}")
            return False
    
    async def get_hash_fields(self, hash_key: str, fields: List[str]) -> Dict[str, Any]:
        """Hash의 여러 필드 한번에 조회"""
        try:
            values = await self.redis_client.hmget(hash_key, fields)
            
            result = {}
            for i, field in enumerate(fields):
                if values[i] is not None:
                    value = values[i]
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    
                    try:
                        result[field] = json.loads(value)
                    except json.JSONDecodeError:
                        # JSON 파싱 실패시 원본 값 사용
                        result[field] = value
            
            self.logger.debug(f"Retrieved {len(result)} fields from hash {hash_key}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting hash fields from {hash_key}: {e}")
            return {}
    
    async def get_hash_length(self, hash_key: str) -> int:
        """Hash의 필드 개수 조회"""
        try:
            return await self.redis_client.hlen(hash_key)
        except Exception as e:
            self.logger.error(f"Error getting hash length for {hash_key}: {e}")
            return 0
    
    async def hash_exists_field(self, hash_key: str, field: str) -> bool:
        """Hash에 특정 필드 존재 여부 확인"""
        try:
            return bool(await self.redis_client.hexists(hash_key, str(field)))
        except Exception as e:
            self.logger.error(f"Error checking hash field existence: {e}")
            return False
    
    # === 배치 작업 메서드들 ===
    
    async def set_multiple(self, data_dict: Dict[str, Any], expire_time: Optional[int] = None) -> bool:
        """여러 키-값 쌍을 한번에 설정"""
        try:
            expire_time = expire_time or self.default_expire_time
            
            pipeline = self.redis_client.pipeline()
            
            for key, value in data_dict.items():
                serialized_value = json.dumps(value, default=str)
                pipeline.setex(key, expire_time, serialized_value)
            
            results = await pipeline.execute()
            
            success_count = sum(1 for result in results if result)
            self.logger.debug(f"Set {success_count}/{len(data_dict)} cache entries")
            
            return success_count == len(data_dict)
            
        except Exception as e:
            self.logger.error(f"Error setting multiple cache entries: {e}")
            return False
    
    async def get_multiple(self, keys: List[str]) -> Dict[str, Any]:
        """여러 키의 값을 한번에 조회"""
        try:
            values = await self.redis_client.mget(keys)
            
            result = {}
            for i, key in enumerate(keys):
                if values[i] is not None:
                    value = values[i]
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = value
            
            self.logger.debug(f"Retrieved {len(result)} cache entries")
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting multiple cache entries: {e}")
            return {}
    
    async def delete_multiple(self, keys: List[str]) -> int:
        """여러 키를 한번에 삭제"""
        try:
            if not keys:
                return 0
            
            deleted_count = await self.redis_client.delete(*keys)
            
            self.logger.debug(f"Deleted {deleted_count} cache entries")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error deleting multiple cache entries: {e}")
            return 0
    
    # === 패턴 기반 작업 메서드들 ===
    
    async def delete_by_pattern(self, pattern: str) -> int:
        """패턴에 맞는 키들을 모두 삭제"""
        try:
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                deleted_count = await self.redis_client.delete(*keys)
                self.logger.debug(f"Deleted {deleted_count} keys matching pattern: {pattern}")
                return deleted_count
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error deleting keys by pattern {pattern}: {e}")
            return 0
    
    async def get_keys_by_pattern(self, pattern: str) -> List[str]:
        """패턴에 맞는 키 목록 조회"""
        try:
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                # bytes를 string으로 변환
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
                keys.append(key)
            
            self.logger.debug(f"Found {len(keys)} keys matching pattern: {pattern}")
            return keys
            
        except Exception as e:
            self.logger.error(f"Error getting keys by pattern {pattern}: {e}")
            return []
    
    # === 캐시 정보 및 모니터링 메서드들 ===
    
    async def get_cache_stats(self, key_pattern: Optional[str] = None) -> Dict[str, Any]:
        """캐시 통계 정보 조회"""
        try:
            pattern = key_pattern or "*"
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)
            
            stats = {
                "total_keys": len(keys),
                "pattern": pattern,
                "timestamp": datetime.utcnow().isoformat(),
                "key_details": []
            }
            
            # 각 키의 상세 정보 (최대 100개까지)
            for key in keys[:100]:
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
                
                key_type = await self.redis_client.type(key)
                ttl = await self.redis_client.ttl(key)
                memory_usage = await self._get_memory_usage(key)
                
                key_info = {
                    "key": key,
                    "type": key_type.decode('utf-8') if isinstance(key_type, bytes) else str(key_type),
                    "ttl": ttl,
                    "memory_usage": memory_usage
                }
                stats["key_details"].append(key_info)
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting cache stats: {e}")
            return {"error": str(e), "timestamp": datetime.utcnow().isoformat()}
    
    async def _get_memory_usage(self, key: str) -> Optional[int]:
        """키의 메모리 사용량 조회 (Redis 4.0+)"""
        try:
            return await self.redis_client.memory_usage(key)
        except:
            return None
    
    async def clear_expired_keys(self, pattern: str) -> int:
        """만료된 키들 정리 (TTL이 0 이하인 키들)"""
        try:
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)
            
            expired_keys = []
            
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
                
                ttl = await self.redis_client.ttl(key)
                if ttl == -2:  # 키가 존재하지 않음
                    expired_keys.append(key)
            
            if expired_keys:
                deleted_count = await self.redis_client.delete(*expired_keys)
                self.logger.debug(f"Cleared {deleted_count} expired keys")
                return deleted_count
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error clearing expired keys: {e}")
            return 0