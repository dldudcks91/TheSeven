from sqlalchemy.orm import Session
import models, schemas
from services.system import GameDataManager
from services.game import ResourceManager, BuffManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
import time
from datetime import datetime, timedelta
import logging


class BuildingManager:
    """건물 관리자 - 컴포넌트 기반 구조로 업데이트"""
    
    MAX_LEVEL = 10
    CONFIG_TYPE = 'building'
    AVAILABLE_BUILDINGS = [101, 201, 301, 401]
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None 
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_buildings = None
        self.logger = logging.getLogger(self.__class__.__name__)
        
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_buildings = None

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
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

        building_idx = self.data.get('building_idx')
        if not building_idx:
            return {
                "success": False,  
                "message": f"Missing required fields: building_idx: {building_idx}",  
                "data": {}
            }
        return None
    
    def _format_building_for_cache(self, building_data):
        """캐시용 건물 데이터 포맷팅"""
        try:
            if isinstance(building_data, dict):
                return {
                    "id": building_data.get('id'),
                    "building_idx": building_data.get('building_idx'),
                    "building_lv": building_data.get('building_lv'),
                    "status": building_data.get('status'),
                    "start_time": building_data.get('start_time'),
                    "end_time": building_data.get('end_time'),
                    "last_dt": building_data.get('last_dt'),
                    "cached_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "id": building_data.id,
                    "building_idx": building_data.building_idx,
                    "building_lv": building_data.building_lv,
                    "status": building_data.status,
                    "start_time": building_data.start_time.isoformat() if building_data.start_time else None,
                    "end_time": building_data.end_time.isoformat() if building_data.end_time else None,
                    "last_dt": building_data.last_dt.isoformat() if building_data.last_dt else None,
                    "cached_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            self.logger.error(f"Error formatting building data for cache: {e}")
            return {}
    
    
    
    async def get_user_buildings(self):
        """사용자 건물 데이터를 캐시 우선으로 조회"""
        if self._cached_buildings is not None:
            return self._cached_buildings
        
        user_no = self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            building_redis = self.redis_manager.get_building_manager()
            self._cached_buildings = await building_redis.get_cached_buildings(user_no)
            self.logger.debug(self._cached_buildings)
            if self._cached_buildings:
                self.logger.debug(f"Cache hit: Retrieved {self._cached_buildings} buildings for user {user_no}")
                return self._cached_buildings
            
            # 2. 캐시 미스: DB에서 조회
            buildings_data = self.get_db_buildings(user_no)
            
            if buildings_data['success'] and buildings_data['data']:
                # 3. Redis에 캐싱
                cache_success = await building_redis.cache_user_buildings_data(user_no, buildings_data['data'])
                if cache_success:
                    self.logger.debug(f"Successfully cached {buildings_data['data']} buildings for user {user_no}")
                
                self._cached_buildings = buildings_data['data']
            else:
                self._cached_buildings = {}
                
        except Exception as e:
            self.logger.error(f"Error getting user buildings for user {user_no}: {e}")
            self._cached_buildings = {}
        
        
        return self._cached_buildings
    
    
    
    def get_db_buildings(self, user_no):
        """DB에서 건물 데이터만 순수하게 조회"""
        try:
            building_db = self.db_manager.get_building_manager()
            buildings_result = building_db.get_user_buildings(user_no)
            
            if not buildings_result['success']:
                return buildings_result
            
            # 데이터 포맷팅
            formatted_buildings = {}
            for building in buildings_result['data']:
                building_idx = building['building_idx']
                formatted_buildings[str(building_idx)] = self._format_building_for_cache(building)
            
            return {
                "success": True,
                "message": f"Loaded {len(formatted_buildings)} buildings from database",
                "data": formatted_buildings
            }
            
        except Exception as e:
            self.logger.error(f"Error loading buildings from DB for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    def invalidate_user_building_cache(self, user_no: int):
        """사용자 건물 캐시 무효화"""
        try:
            building_redis = self.redis_manager.get_building_manager()
            cache_invalidated = building_redis.invalidate_building_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_buildings = None
            
            self.logger.debug(f"Cache invalidated for user {user_no}: {cache_invalidated}")
            return cache_invalidated
            
        except Exception as e:
            self.logger.error(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    
    async def register_building_tasks(self, user_no: int = None):
        """
        진행 중인 건물 작업을 완료 큐에 등록
        
        Args:
            user_no: 사용자 번호, None인 경우 인스턴스의 user_no 사용
        """
        if user_no is None:
            user_no = self.user_no
            
        if not user_no:
            self.logger.error("Cannot register building tasks: user_no is not set")
            return False
            
        try:
            building_redis = self.redis_manager.get_building_manager()
            building_db = self.db_manager.get_building_manager()
            
            building_active_data = building_db.get_active_buildings()['data']
            # BuildingRedisManager의 register 메서드 호출
            # (DB에서 진행 중인 건물 조회 + Redis 큐에 등록)
            for data in building_active_data:
                user_no = data['user_no']
                building_idx = data['building_idx']
                end_time = data['end_time']
            await building_redis.add_building_to_queue(user_no,building_idx, end_time)  # executor 불필요 (이미 비동기)
            
            self.logger.debug(f"Registered building tasks for user {user_no}")
            return True
            
        except AttributeError as e:
            self.logger.warning(f"Building task registration not available: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error registering building tasks for user {user_no}: {e}")
            return False
    
    
    #-------------------- 여기서부터 API 관련 로직 ---------------------------------------#
    
    async def building_info(self):
        """건물 정보를 조회합니다 - 캐시 우선 접근"""
        try:
            buildings_data = await self.get_user_buildings()
            
            return  {
                "success": True,
                "message": f"Retrieved {buildings_data} buildings",
                "data": buildings_data
            }
            
        except Exception as e:
            self.logger.error(f"Error getting building info for user {self.user_no}: {e}")
            return  {
                "success": False,
                "message": f"Failed to retrieve building info: {str(e)}",
                "data": {}
            }

    async def building_create(self):
        """새 건물을 생성하고 즉시 완성하여 DB에 저장합니다."""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 중복 체크 (캐시된 데이터에서)
            buildings_data = await self.get_user_buildings()
            existing_building = buildings_data.get(str(building_idx))
            if existing_building:
                return {"success": False, "message": "Building already exists", "data": {}}
            
            # === 전체 트랜잭션 시작 ===
            try:
                current_time = datetime.utcnow()
                
                # 1. 자원 체크 및 소모 (commit 안함)
                base_upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, 1)
                if error_msg:
                    self.db_manager.rollback()
                    return {"success": False, "message": error_msg, "data": {}}
                
                # 2. 건물 생성 (commit 안함)
                building_db = self.db_manager.get_building_manager()
                create_result = building_db.create_building(
                    user_no=user_no,
                    building_idx=building_idx,
                    building_lv=1,
                    status=0,
                    start_time=current_time,
                    end_time=current_time,
                    last_dt=current_time
                )
                
                if not create_result['success']:
                    self.db_manager.rollback()
                    return create_result
                
                # 3. 모든 작업 성공 - 전체 commit
                self.db_manager.commit()
                self.logger.info(f"Building creation transaction committed for user {user_no}, building {building_idx}")
                
            except Exception as transaction_error:
                # 전체 트랜잭션 롤백
                self.db_manager.rollback()
                self.logger.error(f"Building creation transaction failed: {transaction_error}")
                return {
                    "success": False,
                    "message": f"Building creation failed: {str(transaction_error)}",
                    "data": {}
                }
            # === 전체 트랜잭션 끝 ===
            
            # 캐시 업데이트 (DB 작업 완료 후)
            new_building_data = self._format_building_for_cache(create_result['data'])
            
            # Redis 캐시에 새 건물 추가
            building_redis = self.redis_manager.get_building_manager()
            cache_updated = await building_redis.update_cached_building(user_no, building_idx, new_building_data)
            
            # 메모리 캐시에도 추가
            if self._cached_buildings is not None:
                self._cached_buildings[str(building_idx)] = new_building_data
                self.logger.debug(f"Added building {building_idx} to memory cache for user {user_no}")
            
            return { 
                "success": True,
                "message": f"Building {building_idx} created and completed immediately at level 1",
                "data": create_result['data']
            }
            
        except Exception as e:
            self.logger.error(f"Error creating building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building creation failed: {str(e)}",
                "data": {}
            }
    
    async def building_levelup(self):
        """건물 레벨을 업그레이드합니다 - 전체 트랜잭션 처리"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 1. 캐시된 데이터에서 건물 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            
            # 건물 존재 및 상태 확인
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            if building['status'] != 0:
                return {"success": False, "message": "Building is already under construction or upgrade", "data": {}}
                
            if building['building_lv'] >= self.MAX_LEVEL:
                return {"success": False, "message": f"Building is already at maximum level ({self.MAX_LEVEL})", "data": {}}
            
            # === 전체 트랜잭션 시작 ===
            try:
                # 2. 자원 및 시간 처리 (commit 안함)
                base_upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, building['building_lv'] + 1)
                if error_msg:
                    self.db_manager.rollback()
                    return {"success": False, "message": error_msg, "data": {}}
                
                #upgrade_time = self._apply_building_buffs(user_no, base_upgrade_time)
                upgrade_time = base_upgrade_time
                start_time = datetime.utcnow()
                completion_time = start_time + timedelta(seconds=upgrade_time)
                target_level = building['building_lv'] + 1
                
                # 3. 건물 상태 업데이트 (commit 안함)
                building_db_manager = self.db_manager.get_building_manager()
                building_id = building.get('id') or building.get('building_idx')
                
                update_result = building_db_manager.update_building_status(
                    user_no=user_no,  # 권한 확인용
                    building_idx=building_idx,
                    status=2,  # 업그레이드 중
                    start_time=start_time,
                    end_time=completion_time,
                    last_dt=start_time
                )
                
                if not update_result['success']:
                    self.db_manager.rollback()
                    return update_result
                
                # 4. 모든 작업 성공 - 전체 commit
                self.db_manager.commit()
                self.logger.info(f"Building upgrade transaction committed for user {user_no}, building {building_idx}")
                
            except Exception as transaction_error:
                # 전체 트랜잭션 롤백
                self.db_manager.rollback()
                self.logger.error(f"Building upgrade transaction failed: {transaction_error}")
                return {
                    "success": False,
                    "message": f"Building upgrade failed: {str(transaction_error)}",
                    "data": {}
                }
            # === 전체 트랜잭션 끝 ===
            
            # 캐시 및 Redis 업데이트 (DB 작업 완료 후)
            building_redis = self.redis_manager.get_building_manager()
            
            # 캐시에서 건물 상태 업데이트
            updated_building = {
                **building,
                'status': 2,  # 업그레이드 중
                'start_time': start_time.isoformat(),
                'end_time': completion_time.isoformat(),
                'last_dt': start_time.isoformat(),
                'target_level': target_level  # 목표 레벨 추가
            }
            
            # Redis 캐시 업데이트
            await building_redis.update_cached_building(user_no, building_idx, updated_building)
            
            # 메모리 캐시 업데이트
            if self._cached_buildings and str(building_idx) in self._cached_buildings:
                self._cached_buildings[str(building_idx)] = updated_building
            
            # Redis 완료 큐에 작업 등록
            await building_redis.add_building_to_queue(user_no, building_idx, completion_time)
            
            self.logger.info(f"Building {building_idx} upgrade started for user {user_no}: {building['building_lv']} -> {target_level}, completing in {upgrade_time}s")
            
            return {
                "success": True,
                "message": f"Building {building_idx} upgrade started to level {target_level}. Will complete in {upgrade_time} seconds",
                "data": {
                    "building_idx": building_idx,
                    "current_level": building['building_lv'],
                    "target_level": target_level,
                    "upgrade_time": upgrade_time,
                    "completion_time": completion_time.isoformat(),
                    "status": 2
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error starting building upgrade for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building upgrade failed: {str(e)}",
                "data": {}
            }
    
    async def building_cancel(self):
        """건물 건설/업그레이드를 취소합니다."""
        user_no = self.user_no
        
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 캐시된 데이터에서 건물 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            if building['status'] not in [1, 2]:
                return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
            
            # Redis 큐에서 제거
            building_redis = self.redis_manager.get_building_manager()
            queue_removed = await building_redis.remove_building_from_queue(user_no, building_idx)
            
            if not queue_removed:
                self.logger.warning(f"Failed to remove building {building_idx} from completion queue for user {user_no}")
            
            building_db = self.db_manager.get_building_manager()
            building_id = building.get('id') or building.get('building_idx')
            
            # 취소 처리
            if building['status'] == 1:
                # 건설 취소 - 건물 삭제
                delete_result = building_db.delete(building_id)
                if delete_result['success']:
                    message = "Building construction cancelled and removed"
                    building_data = {}
                else:
                    return delete_result
            elif building['status'] == 2:
                # 업그레이드 취소 - 상태만 원복
                update_result = building_db.update(
                    building_id,
                    status=0,
                    start_time=None,
                    end_time=None,
                    last_dt=datetime.utcnow()
                )
                if update_result['success']:
                    message = "Building upgrade cancelled"
                    building_data = update_result['data']
                else:
                    return update_result
            
            # 캐시 무효화
            self.invalidate_user_building_cache(user_no)
            
            return {
                "success": True,
                "message": message,
                "data": building_data
            }
            
        except Exception as e:
            self.logger.error(f"Error cancelling building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building cancellation failed: {str(e)}",
                "data": {}
            }
    
    async def building_speedup(self):
        """건물 건설/업그레이드를 즉시 완료합니다."""
        user_no = self.user_no
        
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 캐시된 데이터에서 건물 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            if building['status'] not in [1, 2]:
                return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
            
            # Redis에서 완료 시간 조회 및 업데이트
            building_redis = self.redis_manager.get_building_manager()
            completion_time = await building_redis.get_building_completion_time(user_no, building_idx)
            if not completion_time:
                return {"success": False, "message": "Building completion time not found", "data": {}}
            
            # 즉시 완료를 위해 현재 시간으로 업데이트
            current_time = datetime.utcnow()
            update_success = await building_redis.update_building_completion_time(user_no, building_idx, current_time)
            
            if not update_success:
                return {"success": False, "message": "Failed to update completion time", "data": {}}
            
            # 캐시에서 해당 건물 업데이트 (선택적)
            await self._update_cached_building(user_no, building_idx, {
                **building,
                'end_time': current_time.isoformat(),
                'updated_at': current_time.isoformat()
            })
            
            return {
                "success": True,
                "message": "Building completion time accelerated. Will complete shortly.",
                "data": building
            }
            
        except Exception as e:
            self.logger.error(f"Error speeding up building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building speedup failed: {str(e)}",
                "data": {}
            }
    
    async def _update_cached_building(self, user_no: int, building_idx: int, updated_data: dict):
        """캐시된 건물 데이터 업데이트"""
        try:
            building_redis = self.redis_manager.get_building_manager()
            cache_updated = await building_redis.update_cached_building(user_no, building_idx, updated_data)
            
            # 메모리 캐시도 업데이트
            if self._cached_buildings and str(building_idx) in self._cached_buildings:
                self._cached_buildings[str(building_idx)].update(updated_data)
            
            return cache_updated
            
        except Exception as e:
            self.logger.error(f"Error updating cached building {building_idx} for user {user_no}: {e}")
            return False
    
    def _handle_resource_transaction(self, user_no, building_idx, target_level):
        """자원 체크 및 소모 - commit하지 않음"""
        try:
            # 설정 조회
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                return None, "Building configuration not found"
            
            if building_idx not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]:
                return None, f"Building {building_idx} configuration not found"
            
            if target_level not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx]:
                return None, f"Level {target_level} configuration not found"
            
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx][target_level]
            costs = required.get('cost', {})
            upgrade_time = required.get('time', 0)
            
            if not costs or upgrade_time <= 0:
                return None, "Invalid building configuration"
            
            # 자원 매니저 초기화
            resource_manager = ResourceManager(self.db_manager)
            
            # 자원 체크 (한 번의 DB 조회로 now_resources에 저장)
            if not resource_manager.check_require_resources(user_no, costs):
                return None, "Need More Resources"
            
            # 자원 소모 (이미 로드된 인스턴스 직접 업데이트) - commit 안함!
            if not resource_manager.consume_resources(user_no, costs):
                return None, "Failed to consume resources"
            
            # commit하지 않고 반환 - 상위에서 전체 트랜잭션 처리
            return upgrade_time, None
            
        except Exception as e:
            self.logger.error(f"Error handling resource transaction for user {user_no}, building {building_idx}, level {target_level}: {e}")
            return None, f"Resource transaction failed: {str(e)}"
    
    def _apply_building_buffs(self, user_no, base_time):
        """건설 시간 버프 적용"""
        try:
            if base_time <= 0:
                return base_time
            
            buff_manager = BuffManager(self.db_manager, self.redis_manager)
            building_speed_buffs = buff_manager.get_active_buffs(user_no, 'building_speed')
            
            if not building_speed_buffs:
                return base_time
            
            total_reduction = 0
            for buff in building_speed_buffs:
                reduction = buff.get('reduction_percent', 0)
                if isinstance(reduction, (int, float)) and reduction > 0:
                    total_reduction += reduction
            
            # 최대 90% 단축으로 제한
            total_reduction = min(total_reduction, 90)
            
            if total_reduction <= 0:
                return base_time
            
            # 시간 단축 적용
            reduced_time = base_time * (1 - total_reduction / 100)
            final_time = max(1, int(reduced_time))  # 최소 1초
            
            self.logger.debug(f"Applied {total_reduction}% building speed buff: {base_time}s -> {final_time}s")
            return final_time
            
        except Exception as e:
            self.logger.error(f"Error applying building buffs for user {user_no}: {e}")
            return base_time
    
    # === 추가 유틸리티 메서드들 ===
    
    def get_building_status(self, building_idx: int):
        """특정 건물의 상세 상태 조회"""
        try:
            user_no = self.user_no
            building_redis = self.redis_manager.get_building_manager()
            
            # 통합 상태 조회 (캐시 + 큐 정보)
            status = building_redis.get_building_status(user_no, building_idx)
            
            return {
                "success": True,
                "message": f"Retrieved status for building {building_idx}",
                "data": status
            }
            
        except Exception as e:
            self.logger.error(f"Error getting building status for {building_idx}: {e}")
            return {
                "success": False,
                "message": f"Failed to get building status: {str(e)}",
                "data": {}
            }
    
    def get_cache_info(self):
        """캐시 정보 조회 (디버깅/모니터링용)"""
        try:
            user_no = self.user_no
            building_redis = self.redis_manager.get_building_manager()
            
            cache_info = building_redis.get_cache_info(user_no)
            
            return {
                "success": True,
                "message": "Cache information retrieved",
                "data": cache_info
            }
            
        except Exception as e:
            self.logger.error(f"Error getting cache info for user {self.user_no}: {e}")
            return {
                "success": False,
                "message": f"Failed to get cache info: {str(e)}",
                "data": {}
            }