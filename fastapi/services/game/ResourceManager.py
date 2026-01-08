from sqlalchemy.orm import Session
import models, schemas 
from services.system import GameDataManager

from services.redis_manager import RedisManager
from services.db_manager import DBManager, ResourceDBManager
from services.redis_manager.resource_redis_manager import ResourceRedisManager
from datetime import datetime, timedelta
import logging
from typing import Dict, Any, Optional


class ResourceManager:
    """
    자원 관리자 - Redis 기반 캐싱 및 원자적 연산 우선 처리
    
    리팩토링 포인트:
    - consume_resources: atomic_consume 사용으로 Race Condition 방지
    - check_require_resources: UI 미리보기 용도로만 유지 (실제 소모 시 사용 X)
    - BuildingManager 패턴과 일관성 유지
    """
    
    RESOURCE_TYPES = ['food', 'wood', 'stone', 'gold', 'ruby']
    API_RESOURCE_INFO = 1011
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.resource_redis: ResourceRedisManager = self.redis_manager.get_resource_manager()
        self.resource_db: ResourceDBManager = self.db_manager.get_resource_manager()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 메모리 캐시 (BuildingManager 패턴)
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
        # user_no 변경 시 메모리 캐시 초기화
        self.now_resources = {}

    # === 캐시 우선 조회 로직 (Redis-Aside Pattern) ===

    async def _load_resources_from_db_and_cache(self, user_no: int) -> Dict[str, int]:
        """DB에서 로드하고 Redis에 캐싱하는 로직"""
        
        db_resource_model = await self.resource_db.get_user_resources(user_no)
        if not db_resource_model:
            self.logger.warning(f"No resources found in DB for user {user_no}. Initializing to zero.")
            return {res_type: 0 for res_type in self.RESOURCE_TYPES}
            
        resources_dict = {
            res_type: getattr(db_resource_model, res_type, 0)
            for res_type in self.RESOURCE_TYPES
        }
        
        # Redis에 캐싱 (추상화된 메서드 사용)
        await self.resource_redis.cache_user_resources_data(user_no, resources_dict)
        self.logger.info(f"DB Load & Cache: Loaded {resources_dict} for user {user_no}")
        
        return resources_dict

    async def _get_resources(self, user_no: int) -> Dict[str, int]:
        """자원 조회 헬퍼 메서드 (캐시 우선 로직)"""
        # 1. 메모리 캐시 확인
        if self._user_no == user_no and self.now_resources:
            return self.now_resources

        # 2. Redis에서 조회 (추상화된 메서드 사용)
        redis_resources = await self.resource_redis.get_cached_all_resources(user_no)
        
        if redis_resources:
            self.now_resources = redis_resources
            self.logger.debug(f"Cache Hit: Loaded {self.now_resources} from Redis for user {user_no}")
            return self.now_resources
        
        # 3. 캐시 미스: DB에서 로드 후 Redis에 캐싱
        self.now_resources = await self._load_resources_from_db_and_cache(user_no)
        return self.now_resources

    # === 비즈니스 로직 ===
    
    async def resource_info(self) -> Dict[str, Any]:
        """자원 정보를 조회합니다 (Redis 우선)"""
        user_no = self.user_no
        try:
            resources_data = await self._get_resources(user_no)
            
            if not resources_data:
                return {
                    "success": False,
                    "message": "User resources not found",
                    "data": {}
                }
            
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

    # === 원자적 자원 변경 로직 ===
    
    async def consume_resources(self, user_no: int, costs: Dict[str, int]) -> Dict[str, Any]:
        """
        ⭐ 자원 소모 (원자적 검사 + 차감)
        
        변경사항: 
        - atomic_consume 사용으로 Race Condition 방지
        - 검사와 차감이 하나의 원자적 연산으로 처리됨
        
        Args:
            costs: {'food': 100, 'wood': 50, ...}
            
        Returns:
            성공: {"success": True, "remaining": {...}, "consumed": {...}}
            실패: {"success": False, "reason": "insufficient", "shortage": {...}}
        """
        if not costs:
            return {"success": True, "remaining": {}, "consumed": {}}
        
        # 캐시가 없으면 먼저 로드
        if not self.now_resources or self._user_no != user_no:
            await self._get_resources(user_no)
        
        # 원자적 소모 (ResourceRedisManager의 Lua 스크립트 사용)
        result = await self.resource_redis.atomic_consume(user_no, costs)
        
        if result["success"]:
            # 메모리 캐시 업데이트
            if self._user_no == user_no:
                self.now_resources.update(result["remaining"])
            
            result["consumed"] = costs
            self.logger.info(f"Successfully consumed resources for user {user_no}: {costs}")
        else:
            self.logger.warning(f"Failed to consume resources for user {user_no}: {result}")
        
        return result

    async def produce_resources(self, user_no: int, gains: Dict[str, int]) -> Dict[str, Any]:
        """
        자원 생산/획득
        
        Args:
            gains: {'food': 100, 'wood': 50, ...}
            
        Returns:
            {"success": True, "new_amounts": {...}, "produced": {...}}
        """
        if not gains:
            return {"success": True, "new_amounts": {}, "produced": {}}
        
        result = await self.resource_redis.produce_resources(user_no, gains)
        
        if result["success"]:
            # 메모리 캐시 업데이트
            if self._user_no == user_no:
                self.now_resources.update(result["new_amounts"])
            
            result["produced"] = gains
            self.logger.info(f"Successfully produced resources for user {user_no}: {gains}")
        
        return result
    
    async def add_resource(self, user_no: int, resource_type: str, amount: int) -> Optional[int]:
        """단일 자원 추가 (하위 호환성 유지)"""
        if amount <= 0:
            return None
            
        new_amount = await self.resource_redis.change_resource_amount(user_no, resource_type, amount)
        
        if new_amount is not None and self._user_no == user_no:
            self.now_resources[resource_type] = new_amount
            
        return new_amount

    async def check_require_resources(self, user_no: int, costs: Dict[str, int]) -> bool:
        """
        ⚠️ UI 미리보기 용도 - 실제 소모 시에는 consume_resources 사용
        
        필요한 자원이 충분한지 확인합니다.
        
        NOTE: 이 함수는 읽기 전용이므로, consume_resources와 분리 호출 시 
        Race Condition이 발생할 수 있습니다.
        실제 자원 소모 시에는 반드시 consume_resources만 사용하세요.
        """
        resources = await self._get_resources(user_no)
        
        if not resources:
            self.logger.warning(f"No resources found for user {user_no}")
            return False
            
        for resource_type in self.RESOURCE_TYPES:
            now_amount = resources.get(resource_type, 0)
            required_amount = costs.get(resource_type, 0)
            
            if now_amount < required_amount:
                self.logger.debug(
                    f"Insufficient {resource_type} for user {user_no}: "
                    f"need {required_amount}, have {now_amount}"
                )
                return False
                
        return True

    async def get_shortage_info(self, user_no: int, costs: Dict[str, int]) -> Dict[str, Any]:
        """
        부족한 자원 상세 정보 조회 (UI 표시용)
        
        Returns:
            {
                "sufficient": True/False,
                "shortage": {"food": {"required": 100, "current": 50, "needed": 50}, ...}
            }
        """
        resources = await self._get_resources(user_no)
        
        if not resources:
            return {
                "sufficient": False,
                "shortage": {rt: {"required": costs.get(rt, 0), "current": 0, "needed": costs.get(rt, 0)} 
                            for rt in costs}
            }
        
        shortage = {}
        for resource_type, required in costs.items():
            current = resources.get(resource_type, 0)
            if current < required:
                shortage[resource_type] = {
                    "required": required,
                    "current": current,
                    "needed": required - current
                }
        
        return {
            "sufficient": len(shortage) == 0,
            "shortage": shortage
        }

    # === 캐시 관리 ===
    
    async def invalidate_resource_cache(self, user_no: int) -> bool:
        """메모리 캐시 무효화 (BuildingManager 패턴)"""
        if self._user_no == user_no:
            self.now_resources = {}
        
        self.logger.debug(f"Resource memory cache invalidated for user {user_no}")
        return True

    async def get_resource_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅용)"""
        return await self.resource_redis.get_cache_info(user_no)