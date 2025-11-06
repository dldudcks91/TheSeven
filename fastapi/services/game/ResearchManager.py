# ResearchManager.py

from typing import Dict, Any
from sqlalchemy.orm import Session
import models, schemas
from services.system.GameDataManager import GameDataManager
from services.game import ResourceManager, BuffManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime, timedelta
import logging


'''
Research와 Building/Unit의 주요 차이점:

1. 큐 시스템
   - Building: 단일 큐 (한 번에 하나만)
   - Unit: 타입별 큐 (보병/기병/궁병 각각)
   - Research: 단일 큐 (한 번에 하나만) ← Building과 유사

2. 완료 후 처리
   - Building: 레벨 증가, 건물 계속 존재
   - Unit: 수량 증가, 유닛 계속 존재
   - Research: 버프 적용, 완료 상태로만 존재 (더 이상 진행 불가)

3. 반복 가능 여부
   - Building: 레벨업 가능 (MAX_LEVEL까지)
   - Unit: 무한 반복 (계속 훈련 가능)
   - Research: 대부분 1회만 (일부 반복 연구 제외)

4. 선행 조건
   - Building: 자원만
   - Unit: 건물 레벨 필요
   - Research: 선행 연구 필요 (연구 트리)

status 값:
0: 완료됨 (COMPLETED)
1: 진행중 (PROCESSING)
2: 연구 가능 (AVAILABLE)
3: 잠김 (LOCKED - 선행 연구 미완료)
'''

class ResearchManager:
    CONFIG_TYPE = 'research'
    
    # 연구 상태 상수
    STATUS_COMPLETED = 0
    STATUS_PROCESSING = 1
    STATUS_AVAILABLE = 2
    STATUS_LOCKED = 3
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_researches = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        """사용자 번호의 getter"""
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        """사용자 번호의 setter. 정수형인지 확인"""
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_researches = None

    @property
    def data(self):
        """요청 데이터의 getter"""
        return self._data

    @data.setter
    def data(self, value: dict):
        """요청 데이터의 setter. 딕셔너리인지 확인"""
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
    
    def _validate_input(self):
        """공통 입력값 검증"""
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }
        
        research_idx = self.data.get('research_idx')
        if not research_idx:
            return {
                "success": False,
                "message": f"Missing required fields: research_idx: {research_idx}",
                "data": {}
            }
        
        return None
    
    def _format_research_for_cache(self, research_data):
        """캐시용 연구 데이터 포맷팅"""
        try:
            if isinstance(research_data, dict):
                return {
                    "id": research_data.get('id'),
                    "user_no": research_data.get('user_no'),
                    "research_idx": research_data.get('research_idx'),
                    "status": research_data.get('status'),
                    "level": research_data.get('level', 1),
                    "started_at": research_data.get('started_at'),
                    "complete_at": research_data.get('complete_at'),
                    "cached_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "id": research_data.id,
                    "user_no": research_data.user_no,
                    "research_idx": research_data.research_idx,
                    "status": research_data.status,
                    "level": research_data.level or 1,
                    "started_at": research_data.started_at.isoformat() if research_data.started_at else None,
                    "complete_at": research_data.complete_at.isoformat() if research_data.complete_at else None,
                    "cached_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            self.logger.error(f"Error formatting research data for cache: {e}")
            return {}
    
    async def get_user_researches(self):
        """
        사용자 연구 데이터를 캐시 우선으로 조회
        Returns: {research_idx: research_data}
        """
        try:
            if self._cached_researches is not None:
                return self._cached_researches
            
            research_redis = self.redis_manager.get_research_manager()
            cached_data = await research_redis.get_cached_researches(self.user_no)
            
            if cached_data:
                self._cached_researches = cached_data
                return cached_data
            
            # DB에서 조회
            research_db = self.db_manager.get_research_manager()
            researches = research_db.get_user_researches(self.user_no)
            
            researches_dict = {}
            for research in researches:
                formatted = self._format_research_for_cache(research)
                researches_dict[str(research.research_idx)] = formatted
            
            # Redis에 캐싱
            if researches_dict:
                await research_redis.cache_user_researches_data(self.user_no, researches_dict)
            
            self._cached_researches = researches_dict
            return researches_dict
            
        except Exception as e:
            self.logger.error(f"Error getting user researches: {e}")
            return {}
    
    async def _invalidate_cache(self, user_no: int = None):
        """캐시 무효화"""
        try:
            if user_no is None:
                user_no = self.user_no
            
            research_redis = self.redis_manager.get_research_manager()
            cache_invalidated = await research_redis.invalidate_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_researches = None
            
            self.logger.debug(f"Cache invalidated for user {user_no}: {cache_invalidated}")
            return cache_invalidated
            
        except Exception as e:
            self.logger.error(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    async def _format_research_data(self, research_idx):
        """연구 데이터를 응답 형태로 포맷팅 (캐시에서 조회)"""
        researches_data = await self.get_user_researches()
        research = researches_data.get(str(research_idx))
        
        if not research:
            return None
        
        # Redis에서 실제 완료 시간 조회
        redis_completion_time = None
        try:
            research_redis = self.redis_manager.get_research_manager()
            redis_completion_time = await research_redis.get_research_completion_time(
                self.user_no, research_idx
            )
        except Exception as redis_error:
            self.logger.error(f"Redis error: {redis_error}")
        
        return {
            **research,
            "task_completion_time": redis_completion_time.isoformat() if redis_completion_time else None
        }
    
    def _get_research(self, user_no, research_idx):
        """연구 조회"""
        research_db = self.db_manager.get_research_manager()
        return research_db.get_research(user_no, research_idx)
    
    def _get_all_user_researches(self, user_no):
        """사용자의 모든 연구 조회"""
        research_db = self.db_manager.get_research_manager()
        return research_db.get_all_user_researches(user_no)
    
    def _get_current_research(self, user_no):
        """현재 진행중인 연구 반환"""
        research_db = self.db_manager.get_research_manager()
        return research_db.get_current_research(user_no)
    
    async def _ensure_research_exists(self, user_no: int, research_idx: int) -> dict:
        """연구 데이터 존재 확인 및 생성"""
        researches_data = await self.get_user_researches()
        research = researches_data.get(str(research_idx))
        
        if research:
            return research
        
        # 없으면 생성 (초기 상태: AVAILABLE 또는 LOCKED)
        self.logger.info(f"Creating initial research data for user {user_no}, research {research_idx}")
        
        # 선행 연구 확인
        initial_status = await self._check_research_availability(user_no, research_idx)
        
        research_db = self.db_manager.get_research_manager()
        create_result = research_db.create_research(
            user_no=user_no,
            research_idx=research_idx,
            status=initial_status,
            level=0
        )
        
        if not create_result['success']:
            raise Exception("Failed to create research")
        
        self.db_manager.commit()
        
        # 캐시 갱신
        new_research = self._format_research_for_cache(create_result['data'])
        await self._update_cached_research(user_no, research_idx, new_research)
        
        return new_research
    
    async def _check_research_availability(self, user_no: int, research_idx: int) -> int:
        """
        연구 가능 여부 확인
        Returns: STATUS_AVAILABLE or STATUS_LOCKED
        """
        try:
            # CSV에서 선행 연구 정보 가져오기
            config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(research_idx)
            if not config:
                return self.STATUS_LOCKED
            
            prerequisite = config.get('prerequisite_research')
            if not prerequisite or prerequisite == 0:
                return self.STATUS_AVAILABLE
            
            # 선행 연구 완료 확인
            researches_data = await self.get_user_researches()
            prereq_research = researches_data.get(str(prerequisite))
            
            if prereq_research and prereq_research.get('status') == self.STATUS_COMPLETED:
                return self.STATUS_AVAILABLE
            
            return self.STATUS_LOCKED
            
        except Exception as e:
            self.logger.error(f"Error checking research availability: {e}")
            return self.STATUS_LOCKED
    
    async def _has_ongoing_research(self, user_no):
        """진행중인 연구가 있는지 확인 (Redis 기반)"""
        try:
            research_redis = self.redis_manager.get_research_manager()
            completion_time = await research_redis.get_research_completion_time(user_no)
            if completion_time:
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error checking ongoing research in Redis: {e}")
            return False
    
    async def _handle_resource_transaction(self, user_no, research_idx):
        """자원 체크 및 소모를 한번에 처리"""
        try:
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][research_idx]
            costs = required['cost']
            base_time = required['time']
            
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            if not await resource_manager.check_require_resources(user_no, costs):
                return None, "Need More Resources"
            
            await resource_manager.consume_resources(user_no, costs)
            return base_time, None
            
        except Exception as e:
            return None, f"Resource error: {str(e)}"
    
    def _apply_research_buffs(self, user_no, base_time):
        """연구 시간 버프 적용"""
        try:
            buff_manager = BuffManager(self.db_manager, self.redis_manager)
            buffs = buff_manager.get_active_buffs(user_no, 'research_speed')
            
            total_reduction = 0
            for buff in buffs:
                total_reduction += buff.get('reduction_percent', 0)
            
            # 최대 90% 단축으로 제한
            total_reduction = min(total_reduction, 90)
            
            # 시간 단축 적용
            reduced_time = base_time * (1 - total_reduction / 100)
            return max(1, int(reduced_time))  # 최소 1초
            
        except Exception as e:
            self.logger.error(f"Error applying research buffs: {e}")
            return base_time
    
    async def _update_cached_research(self, user_no: int, research_idx: int, updated_data: dict):
        """캐시된 연구 데이터 업데이트"""
        try:
            research_redis = self.redis_manager.get_research_manager()
            cache_updated = await research_redis.update_cached_research(user_no, research_idx, updated_data)
            return cache_updated
        except Exception as e:
            self.logger.error(f"Error updating cached research {research_idx} for user {user_no}: {e}")
            return False
    
    async def research_info(self):
        """
        연구 정보를 조회합니다.
        Returns: 모든 연구의 상태 정보
        """
        try:
            researches_data = await self.get_user_researches()
            
            # 각 연구에 task_completion_time 추가
            enriched_researches = {}
            for research_idx, research in researches_data.items():
                formatted = await self._format_research_data(int(research_idx))
                if formatted:
                    enriched_researches[research_idx] = formatted
            
            return {
                "success": True,
                "message": f"Retrieved {len(enriched_researches)} researches",
                "data": enriched_researches
            }
        except Exception as e:
            self.logger.error(f"Error getting research info: {e}")
            return {
                "success": False,
                "message": f"Error retrieving research info: {str(e)}",
                "data": {}
            }
    
    async def research_start(self):
        """연구를 시작합니다."""
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            research_idx = self.data.get('research_idx')
            
            if not research_idx:
                return {"success": False, "message": "Missing research_idx", "data": {}}
            
            # 진행중인 연구가 있는지 확인 (한 번에 하나만)
            if await self._has_ongoing_research(user_no):
                return {
                    "success": False, 
                    "message": "Another research is already in progress", 
                    "data": {}
                }
            
            # 연구 존재 확인 및 생성
            research = await self._ensure_research_exists(user_no, research_idx)
            
            # 이미 완료된 연구인지 확인
            if research.get('status') == self.STATUS_COMPLETED:
                # 반복 가능한 연구인지 확인
                config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(research_idx)
                if not config.get('repeatable', False):
                    return {
                        "success": False,
                        "message": "This research is already completed and not repeatable",
                        "data": {}
                    }
            
            # 연구 가능 상태인지 확인
            if research.get('status') == self.STATUS_LOCKED:
                return {
                    "success": False,
                    "message": "Prerequisite research not completed",
                    "data": {}
                }
            
            # 자원 처리
            base_time, error_msg = await self._handle_resource_transaction(user_no, research_idx)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 버프 적용된 시간 계산
            research_time = self._apply_research_buffs(user_no, base_time)
            
            # 시간 설정
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=research_time)
            
            # Redis 완료 큐에 추가
            research_redis = self.redis_manager.get_research_manager()
            await research_redis.add_research_to_queue(
                user_no, 
                research_idx, 
                completion_time
            )
            
            # Redis 캐시 업데이트
            updated_research = {
                **research,
                'status': self.STATUS_PROCESSING,
                'started_at': start_time.isoformat(),
                'complete_at': completion_time.isoformat(),
                'cached_at': datetime.utcnow().isoformat()
            }
            await self._update_cached_research(user_no, research_idx, updated_research)
            
            return {
                "success": True,
                "message": f"Started research. Will complete in {research_time} seconds",
                "data": await self._format_research_data(research_idx)
            }
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error starting research: {e}")
            return {
                "success": False, 
                "message": f"Error starting research: {str(e)}", 
                "data": {}
            }
    
    async def research_finish(self):
        """
        연구를 완료합니다. (타이머 만료 시 자동 호출)
        
        Building/Unit과의 차이점:
        - Building: level 증가
        - Unit: ready 수량 증가
        - Research: status를 COMPLETED로 변경하고 버프 적용
        """
        try:
            user_no = self.user_no
            
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            research_idx = self.data.get('research_idx')
            
            # 캐시에서 연구 정보 조회
            researches_data = await self.get_user_researches()
            research = researches_data.get(str(research_idx))
            
            if not research:
                return {"success": False, "message": "Research not found", "data": {}}
            
            if research.get('status') != self.STATUS_PROCESSING:
                return {
                    "success": False, 
                    "message": "Research is not in progress", 
                    "data": {}
                }
            
            # 완료 시간 확인
            complete_at = research.get('complete_at')
            if complete_at:
                complete_time = datetime.fromisoformat(complete_at)
                if datetime.utcnow() < complete_time:
                    return {
                        "success": False,
                        "message": "Research not yet completed",
                        "data": {}
                    }
            
            # DB 업데이트
            research_db = self.db_manager.get_research_manager()
            
            # 반복 가능한 연구인 경우 level 증가
            config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(research_idx)
            new_level = research.get('level', 0) + 1
            
            update_result = research_db.complete_research(
                user_no=user_no,
                research_idx=research_idx,
                level=new_level
            )
            
            if not update_result['success']:
                return update_result
            
            self.db_manager.commit()
            
            # Redis 큐에서 제거
            research_redis = self.redis_manager.get_research_manager()
            await research_redis.remove_research_from_queue(user_no, research_idx)
            
            # 버프 적용
            buff_manager = BuffManager(self.db_manager, self.redis_manager)
            buff_manager.user_no = user_no
            await buff_manager.apply_research_buffs(research_idx, new_level)
            
            # 선행 연구로 사용하는 다른 연구들의 상태 업데이트
            await self._unlock_dependent_researches(user_no, research_idx)
            
            # 캐시 무효화
            await self._invalidate_cache(user_no)
            
            return {
                "success": True,
                "message": f"Research completed successfully at level {new_level}",
                "data": await self._format_research_data(research_idx)
            }
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error completing research: {e}")
            return {
                "success": False,
                "message": f"Error completing research: {str(e)}",
                "data": {}
            }
    
    async def _unlock_dependent_researches(self, user_no: int, completed_research_idx: int):
        """
        완료된 연구를 선행 조건으로 하는 연구들을 잠금 해제
        """
        try:
            # 모든 연구 설정을 순회하며 선행 연구가 방금 완료된 연구인지 확인
            all_configs = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]
            
            for research_idx, config in all_configs.items():
                prereq = config.get('prerequisite_research')
                if prereq == completed_research_idx:
                    # 해당 연구의 상태를 AVAILABLE로 변경
                    research = await self._ensure_research_exists(user_no, research_idx)
                    if research.get('status') == self.STATUS_LOCKED:
                        updated_research = {
                            **research,
                            'status': self.STATUS_AVAILABLE,
                            'cached_at': datetime.utcnow().isoformat()
                        }
                        await self._update_cached_research(user_no, research_idx, updated_research)
                        
                        # DB도 업데이트
                        research_db = self.db_manager.get_research_manager()
                        research_db.update_research_status(
                            user_no, 
                            research_idx, 
                            self.STATUS_AVAILABLE
                        )
            
            self.db_manager.commit()
            
        except Exception as e:
            self.logger.error(f"Error unlocking dependent researches: {e}")
    
    async def research_cancel(self):
        """
        연구를 취소합니다. (일부 자원 환불)
        """
        try:
            user_no = self.user_no
            
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            research_idx = self.data.get('research_idx')
            refund_percent = self.data.get('refund_percent', 50)  # 기본 50% 환불
            
            # 진행중인 연구 확인
            researches_data = await self.get_user_researches()
            research = researches_data.get(str(research_idx))
            
            if not research or research.get('status') != self.STATUS_PROCESSING:
                return {
                    "success": False,
                    "message": "No research in progress to cancel",
                    "data": {}
                }
            
            # 자원 환불
            config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][research_idx]
            costs = config['cost']
            
            refund_resources = {}
            for resource, cost in costs.items():
                refund_resources[resource] = int(cost * refund_percent / 100)
            
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            await resource_manager.add_resources(user_no, refund_resources)
            
            # 연구 상태 업데이트
            research_db = self.db_manager.get_research_manager()
            research_db.update_research_status(
                user_no,
                research_idx,
                self.STATUS_AVAILABLE
            )
            
            self.db_manager.commit()
            
            # Redis 큐에서 제거
            research_redis = self.redis_manager.get_research_manager()
            await research_redis.remove_research_from_queue(user_no, research_idx)
            
            # 캐시 무효화
            await self._invalidate_cache(user_no)
            
            return {
                "success": True,
                "message": f"Research cancelled. Refunded {refund_percent}% of resources",
                "data": {
                    "refunded": refund_resources
                }
            }
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error cancelling research: {e}")
            return {
                "success": False,
                "message": f"Error cancelling research: {str(e)}",
                "data": {}
            }
    
    async def research_instant_complete(self):
        """
        연구를 즉시 완료합니다. (다이아 소비)
        """
        try:
            user_no = self.user_no
            
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            research_idx = self.data.get('research_idx')
            
            # 진행중인 연구 확인
            researches_data = await self.get_user_researches()
            research = researches_data.get(str(research_idx))
            
            if not research or research.get('status') != self.STATUS_PROCESSING:
                return {
                    "success": False,
                    "message": "No research in progress to complete",
                    "data": {}
                }
            
            # 남은 시간 계산
            complete_at = datetime.fromisoformat(research.get('complete_at'))
            remaining_seconds = max(0, (complete_at - datetime.utcnow()).total_seconds())
            
            # 다이아 비용 계산 (예: 1분당 1다이아)
            diamond_cost = max(1, int(remaining_seconds / 60))
            
            # 다이아 확인 및 소비
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            diamond_check = await resource_manager.check_require_resources(
                user_no, 
                {'diamond': diamond_cost}
            )
            
            if not diamond_check:
                return {
                    "success": False,
                    "message": f"Not enough diamonds. Required: {diamond_cost}",
                    "data": {}
                }
            
            await resource_manager.consume_resources(user_no, {'diamond': diamond_cost})
            
            # 연구 즉시 완료
            self.data['research_idx'] = research_idx
            complete_result = await self.research_complete()
            
            if complete_result['success']:
                complete_result['data']['diamond_used'] = diamond_cost
                complete_result['message'] = f"Research instantly completed using {diamond_cost} diamonds"
            
            return complete_result
            
        except Exception as e:
            self.db_manager.rollback()
            self.logger.error(f"Error instant completing research: {e}")
            return {
                "success": False,
                "message": f"Error instant completing research: {str(e)}",
                "data": {}
            }