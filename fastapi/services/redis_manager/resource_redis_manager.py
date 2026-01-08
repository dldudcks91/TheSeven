from datetime import datetime
from typing import Optional, Dict, Any, List
from .base_redis_cache_manager import BaseRedisCacheManager 
from .redis_types import CacheType
import logging


class ResourceRedisManager:
    """
    자원 전용 Redis 관리자 - Hash 구조 사용 (비동기 버전)
    
    리팩토링 포인트:
    - BaseRedisCacheManager의 추상화 메서드 활용 (키 직접 생성 제거)
    - redis_client 직접 호출 최소화
    - atomic_consume: Lua 스크립트로 검사+차감 원자적 처리
    
    SOLID 원칙 준수:
    - SRP: 키 생성은 BaseRedisCacheManager가 담당
    - OCP: 키 포맷 변경 시 BaseRedisCacheManager만 수정
    - DIP: redis_client 직접 사용 대신 추상화된 Manager 사용
    """
    
    # 게임에서 사용하는 자원 목록
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    
    def __init__(self, redis_client):
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.RESOURCES)
        self.redis_client = redis_client  # Lua 스크립트 실행용
        self.cache_expire_time = 3600 * 24 * 7  # 7일
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Lua 스크립트 등록 (원자적 자원 소모용)
        self._register_lua_scripts()
    
    def _register_lua_scripts(self):
        """Lua 스크립트 등록"""
        # 원자적 자원 소모 스크립트
        # 모든 자원이 충분한지 확인 후 일괄 차감
        self._atomic_consume_script = """
        local hash_key = KEYS[1]
        local num_resources = tonumber(ARGV[1])
        
        -- 1단계: 모든 자원 잔액 확인
        for i = 1, num_resources do
            local resource_type = ARGV[2 + (i-1) * 2]
            local cost = tonumber(ARGV[3 + (i-1) * 2])
            
            local current = tonumber(redis.call('HGET', hash_key, resource_type) or 0)
            
            if current < cost then
                -- 자원 부족: 부족한 자원 정보 반환
                return {0, resource_type, cost, current}
            end
        end
        
        -- 2단계: 모든 자원 충분하면 일괄 차감
        local results = {}
        for i = 1, num_resources do
            local resource_type = ARGV[2 + (i-1) * 2]
            local cost = tonumber(ARGV[3 + (i-1) * 2])
            
            local new_amount = redis.call('HINCRBY', hash_key, resource_type, -cost)
            table.insert(results, resource_type)
            table.insert(results, new_amount)
        end
        
        -- 성공: {1, resource1, amount1, resource2, amount2, ...}
        table.insert(results, 1, 1)
        return results
        """
        
    def validate_resource_data(self, resource_type: str) -> bool:
        """자원 타입 유효성 검증"""
        return resource_type in self.RESOURCE_TYPES

    # === Hash 기반 캐싱 관리 메서드들 (추상화 활용) ===

    async def cache_user_resources_data(self, user_no: int, resources_data: Dict[str, int]) -> bool:
        """
        Hash 구조로 자원 데이터 캐싱 (DB 로드 후 Warm-up)
        
        변경사항: cache_manager의 추상화 메서드 활용
        """
        if not resources_data:
            return True
        
        try:
            # 추상화된 키 생성 메서드 사용
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'resource_count': len(resources_data),
                'user_no': user_no
            }
            
            # 자원은 정수값이므로 pipeline으로 직접 HSET (JSON 직렬화 불필요)
            # 이 부분은 자원 특성상 redis_client 직접 사용이 적절함
            pipeline = self.redis_client.pipeline()
            
            for resource_type, amount in resources_data.items():
                if resource_type in self.RESOURCE_TYPES:
                    pipeline.hset(hash_key, resource_type, int(amount))
            
            pipeline.expire(hash_key, self.cache_expire_time)
            await pipeline.execute()
            
            # 메타데이터는 cache_manager 통해 저장
            await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
            
            self.logger.info(f"Successfully cached {len(resources_data)} resources for user {user_no}")
            return True
                
        except Exception as e:
            self.logger.error(f"Error caching resources data: {e}")
            return False

    async def get_cached_resource(self, user_no: int, resource_type: str) -> Optional[int]:
        """특정 자원 하나만 캐시에서 조회"""
        if not self.validate_resource_data(resource_type):
            return None
            
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # 정수값 조회는 get_hash_field 대신 직접 hget 사용 (JSON 파싱 불필요)
            value = await self.redis_client.hget(hash_key, resource_type)
            
            if value is not None:
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                return int(value)
            
            return None
                
        except Exception as e:
            self.logger.error(f"Error retrieving cached resource {resource_type} for user {user_no}: {e}")
            return None

    async def get_cached_all_resources(self, user_no: int) -> Optional[Dict[str, int]]:
        """모든 자원을 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            resources_raw = await self.redis_client.hgetall(hash_key)
            
            if resources_raw:
                resources = {}
                for field, value in resources_raw.items():
                    if isinstance(field, bytes):
                        field = field.decode('utf-8')
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    
                    if field in self.RESOURCE_TYPES:
                        resources[field] = int(value)
                
                self.logger.debug(f"Cache hit: Retrieved resources for user {user_no}")
                return resources
            
            self.logger.debug(f"Cache miss: No resources for user {user_no}")
            return None
                
        except Exception as e:
            self.logger.error(f"Error retrieving cached resources for user {user_no}: {e}")
            return None

    # === 핵심: 원자적 자원 연산 메서드들 ===

    async def atomic_consume(self, user_no: int, costs: Dict[str, int]) -> Dict[str, Any]:
        """
        ⭐ 원자적 자원 소모 (Lua 스크립트)
        
        검사와 차감을 하나의 원자적 연산으로 처리하여 Race Condition 방지
        
        Args:
            user_no: 사용자 번호
            costs: {'food': 100, 'wood': 50, ...}
            
        Returns:
            성공: {"success": True, "remaining": {"food": 900, "wood": 450, ...}}
            실패: {"success": False, "reason": "insufficient", "shortage": {"food": {"required": 100, "current": 50}}}
        """
        if not costs:
            return {"success": True, "remaining": {}}
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # Lua 스크립트 인자 준비
            # ARGV: [num_resources, type1, cost1, type2, cost2, ...]
            argv = [len(costs)]
            for resource_type, cost in costs.items():
                if cost <= 0:
                    continue
                if not self.validate_resource_data(resource_type):
                    return {
                        "success": False, 
                        "reason": "invalid_resource_type",
                        "resource_type": resource_type
                    }
                argv.extend([resource_type, cost])
            
            # 실제 소모할 자원이 없으면 성공
            if len(argv) == 1:
                return {"success": True, "remaining": {}}
            
            argv[0] = (len(argv) - 1) // 2  # 실제 자원 수 업데이트
            
            # Lua 스크립트 실행
            result = await self.redis_client.eval(
                self._atomic_consume_script,
                1,  # KEYS 개수
                hash_key,  # KEYS[1]
                *argv  # ARGV
            )
            
            # 결과 파싱
            if result[0] == 1:
                # 성공: 남은 자원량 반환
                remaining = {}
                for i in range(1, len(result), 2):
                    resource_type = result[i]
                    if isinstance(resource_type, bytes):
                        resource_type = resource_type.decode('utf-8')
                    remaining[resource_type] = int(result[i + 1])
                
                self.logger.info(f"Atomic consume success for user {user_no}: {costs}")
                return {"success": True, "remaining": remaining}
            else:
                # 실패: 부족한 자원 정보 반환
                shortage_type = result[1]
                if isinstance(shortage_type, bytes):
                    shortage_type = shortage_type.decode('utf-8')
                    
                self.logger.warning(f"Atomic consume failed for user {user_no}: "
                                   f"insufficient {shortage_type}")
                return {
                    "success": False,
                    "reason": "insufficient",
                    "shortage": {
                        shortage_type: {
                            "required": int(result[2]),
                            "current": int(result[3])
                        }
                    }
                }
                
        except Exception as e:
            self.logger.error(f"Error in atomic_consume for user {user_no}: {e}")
            return {"success": False, "reason": "error", "message": str(e)}

    async def change_resource_amount(self, user_no: int, resource_type: str, amount_change: int) -> Optional[int]:
        """
        특정 자원의 양을 원자적으로 변경 (단일 자원용)
        
        ⚠️ 주의: 여러 자원을 동시에 소모할 때는 atomic_consume 사용 권장
        
        Args:
            amount_change: 증감량 (양수: 획득, 음수: 소모)
            
        Returns:
            변경 후 자원 양, 실패 시 None
        """
        if not self.validate_resource_data(resource_type):
            self.logger.warning(f"Invalid resource type: {resource_type}")
            return None
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # cache_manager의 추상화 메서드 사용
            new_amount = await self.cache_manager.increment_hash_field(
                hash_key, resource_type, amount_change
            )

            if new_amount is not None:
                # 음수 체크: 자원이 부족한 경우 롤백
                if new_amount < 0:
                    await self.cache_manager.increment_hash_field(
                        hash_key, resource_type, -amount_change
                    )
                    self.logger.warning(
                        f"Insufficient resource {resource_type} for user {user_no}. "
                        f"Attempted: {amount_change}, Would result: {new_amount}. Rolled back."
                    )
                    return None
                
                return new_amount
                
            return None

        except Exception as e:
            self.logger.error(f"Error changing resource amount for {resource_type}: {e}")
            return None

    async def produce_resources(self, user_no: int, gains: Dict[str, int]) -> Dict[str, Any]:
        """
        자원 생산/획득 (원자적 증가)
        
        Args:
            gains: {'food': 100, 'wood': 50, ...}
            
        Returns:
            {"success": True, "new_amounts": {"food": 1100, ...}}
        """
        if not gains:
            return {"success": True, "new_amounts": {}}
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            new_amounts = {}
            
            for resource_type, gain in gains.items():
                if gain <= 0:
                    continue
                if not self.validate_resource_data(resource_type):
                    continue
                    
                new_amount = await self.cache_manager.increment_hash_field(
                    hash_key, resource_type, gain
                )
                if new_amount is not None:
                    new_amounts[resource_type] = new_amount
            
            self.logger.info(f"Produced resources for user {user_no}: {gains}")
            return {"success": True, "new_amounts": new_amounts}
            
        except Exception as e:
            self.logger.error(f"Error producing resources for user {user_no}: {e}")
            return {"success": False, "reason": "error", "message": str(e)}

    # === 캐시 무효화 및 유틸리티 ===
    
    async def invalidate_resource_cache(self, user_no: int) -> bool:
        """사용자 자원 캐시 전체 무효화"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            hash_deleted = await self.cache_manager.delete_data(hash_key)
            meta_deleted = await self.cache_manager.delete_data(meta_key)
            
            success = hash_deleted or meta_deleted
            if success:
                self.logger.info(f"Resource cache invalidated for user {user_no}")
            return success
                
        except Exception as e:
            self.logger.error(f"Error invalidating resource cache for user {user_no}: {e}")
            return False

    async def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅/모니터링용)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            resources = await self.get_cached_all_resources(user_no)
            ttl = await self.cache_manager.get_ttl(hash_key)
            meta_data = await self.cache_manager.get_data(meta_key) or {}
            
            return {
                "user_no": user_no,
                "resources": resources,
                "ttl_seconds": ttl,
                "meta_data": meta_data,
                "cache_exists": resources is not None,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting cache info for user {user_no}: {e}")
            return {"user_no": user_no, "cache_exists": False, "error": str(e)}

    # === 컴포넌트 접근 ===
    
    def get_cache_manager(self) -> BaseRedisCacheManager:
        """Cache Manager 컴포넌트 반환"""
        return self.cache_manager