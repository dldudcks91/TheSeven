from sqlalchemy.orm import Session
import models, schemas 
from services.system import GameDataManager

# RedisManager와 DBManager는 그대로 사용
from services.redis_manager import RedisManager
from services.db_manager import DBManager, ResourceDBManager
from services.redis_manager.resource_redis_manager import ResourceRedisManager # 새로 추가된 Redis Manager
import time
from datetime import datetime, timedelta
import logging
from typing import Dict, Any


class ResourceManager:
    """
    자원 관리자 - Redis 기반 캐싱 및 원자적 연산 우선 처리
    - DB는 영속성 및 캐시 미스 시에만 접근합니다.
    - 자원 변경은 Redis의 원자적 연산을 사용하여 동시성 문제를 방지합니다.
    """
    
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    API_RESOURCE_INFO = 1011
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        # ResourceRedisManager 컴포넌트 사용 (자원 Redis 로직 분리)
        self.resource_redis: ResourceRedisManager = self.redis_manager.get_resource_manager()
        self.resource_db: ResourceDBManager = self.db_manager.get_resource_manager()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # now_resources는 더 이상 DB 모델 객체가 아닌, 캐시된 딕셔너리 데이터입니다.
        self.now_resources: Dict[str, int] = {}
        self._user_no: int = None

    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        # user_no가 변경되면 캐시된 자원 정보는 초기화
        self.now_resources = {}

    # === 캐시 우선 조회 로직 (Redis-Aside Pattern) ===

    async def _load_resources_from_db_and_cache(self, user_no: int) -> Dict[str, int]:
        """DB에서 로드하고 Redis에 캐싱하는 로직"""
        
        # 1. DB에서 조회
        db_resource_model = await self.resource_db.get_user_resources(user_no)
        if not db_resource_model:
            self.logger.warning(f"No resources found in DB for user {user_no}. Initializing to zero.")
            # DB에 자원 모델이 없으면 기본값 반환 (혹은 생성 로직 필요)
            return {res_type: 0 for res_type in self.RESOURCE_TYPES}
            
        # 2. 캐시용 딕셔너리로 포맷팅
        resources_dict = {
            res_type: getattr(db_resource_model, res_type, 0)
            for res_type in self.RESOURCE_TYPES
        }
        
        # 3. Redis에 캐싱 (ResourceRedisManager의 cache_user_resources_data 사용)
        await self.resource_redis.cache_user_resources_data(user_no, resources_dict)
        self.logger.info(f"DB Load & Cache: Loaded {resources_dict} for user {user_no}")
        
        return resources_dict

    async def _get_resources(self, user_no: int) -> Dict[str, int]:
        """자원 조회 헬퍼 메서드 (캐시 우선 로직)"""
        if self.now_resources:
            return self.now_resources

        # 1. Redis에서 조회
        redis_resources = await self.resource_redis.get_cached_all_resources(user_no)
        
        if redis_resources:
            # Hash Value가 JSON 문자열일 경우 Dict[str, int]로 변환 필요
            self.now_resources = {k: int(v) for k, v in redis_resources.items() if k in self.RESOURCE_TYPES}
            self.logger.debug(f"Cache Hit: Loaded {self.now_resources} from Redis for user {user_no}")
            return self.now_resources
        
        # 2. 캐시 미스: DB에서 로드 후 Redis에 캐싱
        self.now_resources = await self._load_resources_from_db_and_cache(user_no)
        return self.now_resources

    # === 비즈니스 로직 ===
    
    async def resource_info(self) -> Dict[str, Any]:
        """자원 정보를 조회합니다 (Redis 우선)"""
        user_no = self.user_no
        try:
            # _get_resources는 Redis -> DB 순으로 조회하고 self.now_resources에 저장
            resources_data = await self._get_resources(user_no)
            
            if not resources_data:
                return {
                    "success": False,
                    "message": "User resources not found",
                    "data": {}
                }
            
            # 응답 데이터 포맷팅 (DB 모델 객체 대신 딕셔너리 사용)
            response_data = {"user_no": user_no}
            response_data.update(resources_data)
            
            return {
                "success": True,
                "message": "Retrieved resource info successfully",
                "data": response_data
            }
            
        except Exception as e:
            self.logger.error(f"Error retrieving resource info for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Error retrieving resource info: {str(e)}",
                "data": {}
            }

    # === 원자적 자원 변경 로직 (Redis Transaction/Atomic Operation) ===
    
    async def consume_resources(self, user_no: int, costs: Dict[str, int]) -> bool:
        """
        자원 소모: Redis의 원자적 연산으로 잔액 검사 및 차감을 동시에 처리합니다.
        (메인 DB는 비동기/지연 쓰기로 처리되어야 하므로, 이 함수 내에서 직접 커밋하지 않습니다.)
        """
        
        # 1. 현재 자원 상태를 Redis에서 로드 (잔액 검사용)
        current_resources = await self._get_resources(user_no)
        if not current_resources:
            return False

        # 2. Redis 원자적 트랜잭션 (Multi/Exec 또는 Lua 스크립트) 준비
        # BuildingManager에서 사용된 트랜잭션 방식(DB commit)을 회피하기 위해
        # ResourceManager는 Redis에서 원자적으로 처리 후, DB 기록은 비동기 처리합니다.

        result_amounts = {}
        successful_changes = True

        for resource_type, cost in costs.items():
            if cost <= 0:
                continue
                
            # Redis에선 자원 부족 시 처리를 위해 HINCRBY를 사용합니다.
            # BaseRedisCacheManager의 change_resource_amount가 HINCRBY를 -cost로 호출한다고 가정
            
            # NOTE: change_resource_amount가 단일 String 키를 사용하도록 ResourceRedisManager에서 변경했었으므로,
            # 여기서는 해당 Manager의 메서드를 사용합니다.
            
            # 자원 소모는 음수 값으로 변경 요청
            new_amount = await self.resource_redis.change_resource_amount(user_no, resource_type, -cost)
            
            if new_amount is None or new_amount < 0:
                # 롤백 처리 (HINCRBY는 롤백이 어려우므로, 잔액 검사를 먼저 수행하는 Lua 스크립트 사용이 이상적)
                # 여기서는 'change_resource_amount'가 롤백 능력이 없으므로, 자원 부족으로 판단하고 실패합니다.
                self.logger.warning(f"Failed to consume {resource_type} for user {user_no}: Cost {cost}, Resulting amount {new_amount}")
                successful_changes = False
                break
                
            result_amounts[resource_type] = new_amount

        # 3. 롤백/Commit 처리
        if not successful_changes:
            # 실패 시, 이미 차감된 자원 복구 (필요한 경우만, 실제 게임에선 Lua 스크립트가 더 안전함)
            self.logger.error("Resource consumption failed. Attempting to reverse changes...")
            for res_type, new_amt in result_amounts.items():
                # 이미 차감된 양을 다시 더해 롤백 시도
                await self.resource_redis.change_resource_amount(user_no, res_type, costs.get(res_type, 0))
            return False

        # 4. (옵션) DB에 비동기/지연 쓰기 전파 로직 호출 (생략 가능, 외부 MQ 사용 권장)
        # self.resource_db.schedule_delayed_write(user_no, result_amounts)
        
        # 5. 메모리 캐시 업데이트
        self.now_resources.update(result_amounts)
        self.logger.info(f"Successfully consumed resources for user {user_no} via Redis: {costs}")
        return True

    async def produce_resources(self, user_no: int, gains: Dict[str, int]) -> bool:
        """자원 생산/획득 - Redis의 원자적 연산으로 증가"""
        
        result_amounts = {}
        successful_changes = True
        
        for resource_type, gain in gains.items():
            if gain <= 0:
                continue
                
            # Redis INCRBY 명령을 통해 원자적으로 증가
            new_amount = await self.resource_redis.change_resource_amount(user_no, resource_type, gain)
            
            if new_amount is None:
                successful_changes = False
                break
                
            result_amounts[resource_type] = new_amount

        if not successful_changes:
            self.logger.error("Resource production failed during Redis operation.")
            return False

        # (옵션) DB에 비동기/지연 쓰기 전파 로직 호출
        
        # 메모리 캐시 업데이트
        if self._user_no == user_no:
            self.now_resources.update(result_amounts)
            
        self.logger.info(f"Successfully produced resources for user {user_no} via Redis: {gains}")
        return True
    
    # BuildingManager에서 사용하던 DB 기반의 자원 체크/소모 로직을 Redis 기반으로 대체합니다.
    # BuildingManager의 _handle_resource_transaction 메서드에서는 consume_resources를 호출하도록 수정이 필요합니다.

    async def check_require_resources(self, user_no: int, costs: Dict[str, int]) -> bool:
        """
        필요한 자원이 충분한지 Redis에서 확인합니다.
        
        NOTE: 이 함수는 단순 '읽기'만 하므로, `consume_resources`와 분리되어 있으면 
        Race Condition이 발생할 수 있습니다. BuildingManager의 트랜잭션은 
        `consume_resources`를 호출하는 순간 Redis의 원자성에 의존하도록 해야 합니다.
        """
        resources = await self._get_resources(user_no)
        
        if not resources:
            self.logger.warning(f"No resources found for user {user_no}")
            return False
            
        for resource_type in self.RESOURCE_TYPES:
            now_amount = resources.get(resource_type, 0)
            required_amount = costs.get(resource_type, 0)
            
            if now_amount < required_amount:
                self.logger.debug(f"Insufficient {resource_type} for user {user_no}: need {required_amount}, have {now_amount}")
                return False
                
        return True