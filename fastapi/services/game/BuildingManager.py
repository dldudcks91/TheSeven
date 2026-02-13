from services.system.GameDataManager import GameDataManager
from services.game import ResourceManager, BuffManager, MissionManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime, timedelta
import logging


class BuildingManager:
    """건물 관리자 - Redis 중심 구조 (DB 업데이트는 별도 Task 처리)"""
    
    MAX_LEVEL = 10
    CONFIG_TYPE = 'building'
    AVAILABLE_BUILDINGS = [101, 201, 301, 401]
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        """
        redis_manager: 필수 - 모든 읽기/쓰기에 사용
        db_manager: 선택 - Redis 캐시 미스 시 DB에서 초기 로드용으로만 사용
        """
        self._user_no: int = None 
        self._data: dict = None
        self.redis_manager = redis_manager
        self.db_manager = db_manager  # 초기 로드용으로만 사용
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
    
    async def get_user_buildings(self):
        """Redis에서 사용자 건물 데이터 조회 (Redis 없으면 DB에서 로드 후 캐싱)"""
        if self._cached_buildings is not None:
            return self._cached_buildings
        
        user_no = self.user_no
        
        try:
            # 1. Redis에서 먼저 조회
            building_redis = self.redis_manager.get_building_manager()
            self._cached_buildings = await building_redis.get_cached_buildings(user_no)
            
            if self._cached_buildings:
                self.logger.debug(f"Cache hit: Retrieved {len(self._cached_buildings)} buildings for user {user_no}")
                return self._cached_buildings
            
            # 2. Redis 미스: DB에서 조회 후 Redis에 캐싱
            if self.db_manager:
                buildings_data = self._load_from_db(user_no)
                
                if buildings_data['success'] and buildings_data['data']:
                    # Redis에 캐싱
                    cache_success = await building_redis.cache_user_buildings_data(user_no, buildings_data['data'])
                    if cache_success:
                        self.logger.debug(f"Successfully cached {len(buildings_data['data'])} buildings from DB for user {user_no}")
                    
                    self._cached_buildings = buildings_data['data']
                else:
                    self._cached_buildings = {}
            else:
                self.logger.warning(f"No buildings in Redis and no DB manager provided for user {user_no}")
                self._cached_buildings = {}
                
        except Exception as e:
            self.logger.error(f"Error getting user buildings for user {user_no}: {e}")
            self._cached_buildings = {}
        
        return self._cached_buildings
    
    async def get_user_building_by_idx(self, building_idx):
        """특정 건물 정보를 Redis에서 조회"""
        user_no = self.user_no
        
        try:
            building_redis = self.redis_manager.get_building_manager()
            cached_building = await building_redis.get_cached_building(user_no, building_idx)
            
            if cached_building:
                self.logger.debug(f"Cache hit: Retrieved building {building_idx} for user {user_no}")
                return cached_building
            else:
                # 전체 건물 조회 후 해당 건물만 반환
                all_buildings = await self.get_user_buildings()
                return all_buildings.get(str(building_idx), {})
                
        except Exception as e:
            self.logger.error(f"Error getting building {building_idx} for user {user_no}: {e}")
            return {}
    
    def _load_from_db(self, user_no):
        """DB에서 건물 데이터 로드 (초기 캐싱용)"""
        try:
            if not self.db_manager:
                return {"success": False, "message": "No DB manager", "data": {}}
            
            building_db = self.db_manager.get_building_manager()
            buildings_result = building_db.get_user_buildings(user_no)
            
            if not buildings_result['success']:
                return buildings_result
            
            # 데이터 포맷팅
            formatted_buildings = {}
            for building in buildings_result['data']:
                building_idx = building['building_idx']
                formatted_buildings[str(building_idx)] = self._format_building_data(building)
            
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
    
    def _format_building_data(self, building_data):
        """건물 데이터 포맷팅"""
        try:
            if isinstance(building_data, dict):
                return {
                    
                    "building_idx": building_data.get('building_idx'),
                    "building_lv": building_data.get('building_lv'),
                    "status": building_data.get('status'),
                    "start_time": building_data.get('start_time'),
                    "end_time": building_data.get('end_time'),
                    "last_dt": building_data.get('last_dt'),
                    "target_level": building_data.get('target_level'),
                    "cached_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    
                    "building_idx": building_data.building_idx,
                    "building_lv": building_data.building_lv,
                    "status": building_data.status,
                    "start_time": building_data.start_time.isoformat() if building_data.start_time else None,
                    "end_time": building_data.end_time.isoformat() if building_data.end_time else None,
                    "last_dt": building_data.last_dt.isoformat() if building_data.last_dt else None,
                    "target_level": getattr(building_data, 'target_level', None),
                    "cached_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            self.logger.error(f"Error formatting building data: {e}")
            return {}
    
    async def invalidate_building_cache(self, user_no: int):
        """메모리 캐시만 무효화 (Redis는 유지)"""
        try:
            if self._user_no == user_no:
                self._cached_buildings = None
            
            self.logger.debug(f"Building memory cache invalidated for user {user_no}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error invalidating building cache for user {user_no}: {e}")
            return False
    
    #-------------------- API 관련 로직 ---------------------------------------#
    
    async def building_info(self):
        """건물 정보 조회 - Redis에서 데이터 반환"""
        try:
            buildings_data = await self.get_user_buildings()
            
            return {
                "success": True,
                "message": f"Retrieved {len(buildings_data)} buildings",
                "data": buildings_data
            }
            
        except Exception as e:
            self.logger.error(f"Error getting building info: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def building_create(self):
        """건물 생성 - DB에 직접 삽입하고 Redis에도 캐싱"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 1. 건물이 생성 가능한 목록에 있는지 확인
            if building_idx not in self.AVAILABLE_BUILDINGS:
                return {
                    "success": False,
                    "message": f"Building {building_idx} is not available for creation",
                    "data": {}
                }
            
            # 2. 이미 존재하는지 확인 (Redis)
            buildings_data = await self.get_user_buildings()
            if str(building_idx) in buildings_data:
                return {
                    "success": False,
                    "message": f"Building {building_idx} already exists",
                    "data": buildings_data[str(building_idx)]
                }
            
            # 3. DB 매니저 확인
            if not self.db_manager:
                return {
                    "success": False,
                    "message": "Database manager not available for building creation",
                    "data": {}
                }
            
            # 4. 게임 설정 조회 (레벨 1 설정)
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                return {"success": False, "message": "Building configuration not found", "data": {}}
            
            if building_idx not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]:
                return {"success": False, "message": f"Building {building_idx} config not found", "data": {}}
            
            if 1 not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx]:
                return {"success": False, "message": "Level 1 config not found", "data": {}}
            
            level_1_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx][1]
            costs = level_1_config.get('cost', {})
            base_build_time = level_1_config.get('time', 0)
            
            if not costs or base_build_time <= 0:
                return {"success": False, "message": "Invalid building configuration", "data": {}}
            
            # 5. 자원 버프 적용 / 자원 체크 및 소모 (Redis)
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            
            # comsume_resources로 통일
            # if not await resource_manager.check_require_resources(user_no, costs):
            #     return {"success": False, "message": "Need More Resources", "data": {}}
            
            if not await resource_manager.consume_resources(user_no, costs):
                return {"success": False, "message": "Failed to consume resources", "data": {}}
            
            # 6. 버프 적용
            final_build_time = self._apply_building_buffs(user_no, base_build_time)
            
            # 7. 시간 계산
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(seconds=final_build_time)
            
            # 8. DB에 직접 삽입
            try:
                building_db = self.db_manager.get_building_manager()
                create_result = building_db.create_building(
                    user_no=user_no,
                    building_idx=building_idx,
                    building_lv=0,  # 건설 중이므로 레벨 0
                    status=1,  # 1: 건설 중
                    start_time=start_time,
                    end_time=end_time,
                    last_dt=start_time
                )
                
                if not create_result['success']:
                    # 실패 시 자원 복구는 Task에서 처리하거나 여기서 롤백
                    self.logger.error(f"Failed to create building in DB: {create_result['message']}")
                    return {
                        "success": False,
                        "message": f"Failed to create building: {create_result['message']}",
                        "data": {}
                    }
                
                # DB 커밋
                self.db_manager.commit()
                
                # 9. Redis에도 캐싱
                building_redis = self.redis_manager.get_building_manager()
                new_building = {
                    "id": create_result['data'].get('id'),
                    "building_idx": building_idx,
                    "building_lv": 0,
                    "status": 1,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "last_dt": start_time.isoformat(),
                    "target_level": 1,
                    "cached_at": datetime.utcnow().isoformat()
                }
                
                await building_redis.update_cached_building(user_no, building_idx, new_building)
                
                # 메모리 캐시 무효화
                self._cached_buildings = None
                
                self.logger.info(f"Building created (DB+Redis): user={user_no}, building={building_idx}, time={final_build_time}s")
                
                return {
                    "success": True,
                    "message": f"Building {building_idx} creation started",
                    "data": new_building
                }
                
            except Exception as db_error:
                # DB 에러 시 롤백
                self.db_manager.rollback()
                self.logger.error(f"Database error during building creation: {db_error}")
                return {
                    "success": False,
                    "message": f"Database error: {str(db_error)}",
                    "data": {}
                }
            
        except Exception as e:
            self.logger.error(f"Error creating building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building creation failed: {str(e)}",
                "data": {}
            }

    
    async def building_upgrade(self):
        """건물 업그레이드 - Redis만 업데이트"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 1. Redis에서 건물 정보 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            
            if not building:
                return {
                    "success": False,
                    "message": f"Building {building_idx} not found",
                    "data": {}
                }
            
            # 2. 상태 검증
            if building['status'] != 0:
                return {
                    "success": False,
                    "message": "Building is already in progress",
                    "data": building
                }
            
            current_level = building['building_lv']
            target_level = current_level + 1
            
            if target_level > self.MAX_LEVEL:
                return {
                    "success": False,
                    "message": "Building is at max level",
                    "data": building
                }
            
            # 3. 게임 설정 조회
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                return {"success": False, "message": "Building configuration not found", "data": {}}
            
            if building_idx not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]:
                return {"success": False, "message": f"Building {building_idx} config not found", "data": {}}
            
            if target_level not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx]:
                return {"success": False, "message": f"Level {target_level} config not found", "data": {}}
            
            level_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx][target_level]
            costs = level_config.get('cost', {})
            base_upgrade_time = level_config.get('time', 0)
            
            if not costs or base_upgrade_time <= 0:
                return {"success": False, "message": "Invalid building configuration", "data": {}}
            
            # 4. ⭐ 자원 소모 (원자적 검사 + 차감)
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            consume_result = await resource_manager.consume_resources(user_no, costs)
            
            if not consume_result["success"]:
                # 실패 시 상세 정보 반환
                if consume_result.get("reason") == "insufficient":
                    shortage = consume_result.get("shortage", {})
                    return {
                        "success": False, 
                        "message": "Need More Resources", 
                        "data": {"shortage": shortage}
                    }
                return {
                    "success": False, 
                    "message": "Failed to consume resources", 
                    "data": consume_result
                }
            
            # 5. 버프 적용
            final_upgrade_time = self._apply_building_buffs(user_no, base_upgrade_time)
            
            # 6. 시간 계산
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(seconds=final_upgrade_time)
            
            # 7. Redis 업데이트
            building_redis = self.redis_manager.get_building_manager()
            updated_building = {
                **building,
                'status': 2,  # 업그레이드 중
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'target_level': target_level,
                'last_dt': start_time.isoformat()
            }
            
            await building_redis.update_cached_building(user_no, building_idx, updated_building)
            
            
            
            self.logger.info(f"Building upgrade started (Redis): user={user_no}, building={building_idx}, level={current_level}->{target_level}, time={final_upgrade_time}s")
            
            return {
                "success": True,
                "message": f"Building {building_idx} upgrade to level {target_level} started",
                "data": {
                    **updated_building,
                    "consumed_resources": consume_result.get("consumed", {}),
                    "remaining_resources": consume_result.get("remaining", {})
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error upgrading building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building upgrade failed: {str(e)}",
                "data": {}
            }
    
    async def building_finish(self):
        """건물 업그레이드 완료 - Redis만 업데이트"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 1. Redis에서 건물 정보 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            
            if not building:
                return {
                    "success": False,
                    "message": f"Building {building_idx} not found",
                    "data": {}
                }
            
            # 2. 상태 검증
            if building['status'] not in [1,2]:
                return {
                    "success": False,
                    "message": "Building is not being upgraded",
                    "data": building
                }
            
            # 3. 완료 시간 검증
            end_time_str = building.get('end_time')
            if not end_time_str:
                return {
                    "success": False,
                    "message": "Building has no end time",
                    "data": building
                }
            
            end_time = datetime.fromisoformat(end_time_str)
            now = datetime.utcnow()
            
            if now < end_time:
                remaining = int((end_time - now).total_seconds())
                return {
                    "success": False,
                    "message": f"Building upgrade not yet complete. {remaining}s remaining",
                    "data": building
                }
            
            # 4. 업그레이드 완료 처리 (Redis)
            target_level = building.get('target_level', building['building_lv'] + 1)
            
            building_redis = self.redis_manager.get_building_manager()
            updated_building = {
                **building,
                'status': 0,  # 완료
                'building_lv': target_level,
                'start_time': None,
                'end_time': None,
                'target_level': None,
                'last_dt': now.isoformat()
            }
            
            #캐싱 업데이트
            await building_redis.update_cached_building(user_no, building_idx, updated_building)
            
            #미션 업데이트
            mission_update = None
            try:
                mission_manager = self._get_mission_manager()
                mission_manager.user_no = user_no
                mission_result = await mission_manager.check_building_missions(building_idx)  # ← 기존 메서드 사용
                if mission_result.get('success'):
                    mission_update = mission_result.get('data')
            except Exception as mission_error:
                self.logger.warning(f"Mission update failed (non-critical): {mission_error}")
            
            
            self.logger.info(f"Building upgrade finished (Redis): user={user_no}, building={building_idx}, new_level={target_level}")
            
            return {
                "success": True,
                "message": f"Building {building_idx} upgraded to level {target_level}",
                "data": {
                    "building": updated_building,
                    "mission_update": mission_update  # 미션 업데이트 결과 포함
                        }
            }
            
        except Exception as e:
            self.logger.error(f"Error finishing building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building finish failed: {str(e)}",
                "data": {}
            }
    
    async def finish_all_completed_buildings(self):
        """완료 시간이 지난 모든 건물을 일괄 완료 처리 - Redis만 업데이트"""
        user_no = self.user_no
        
        try:
            # Redis에서 건물 데이터 조회
            buildings_data = await self.get_user_buildings()
            now = datetime.utcnow()
            processed_buildings = []
            
            building_redis = self.redis_manager.get_building_manager()
            
            for idx, building in buildings_data.items():
                if building['status'] == 2:  # 업그레이드 중
                    completion_time_str = building.get('end_time')
                    if not completion_time_str:
                        continue
                    
                    completion_time = datetime.fromisoformat(completion_time_str)
                    if now >= completion_time:
                        target_level = building.get('target_level', building['building_lv'] + 1)
                        
                        # Redis 업데이트
                        updated_building = {
                            **building,
                            'status': 0,
                            'building_lv': target_level,
                            'start_time': None,
                            'end_time': None,
                            'target_level': None,
                            'last_dt': now.isoformat()
                        }
                        
                        await building_redis.update_cached_building(user_no, int(idx), updated_building)
                        
                        processed_buildings.append({
                            'building_idx': int(idx),
                            'new_level': target_level
                        })
                        
                        self.logger.info(f"Building {idx} upgrade auto-finished at level {target_level}")
            
            # 메모리 캐시 무효화
            if processed_buildings:
                self._cached_buildings = None
            
            return {
                "success": True,
                "message": f"Successfully upgraded {len(processed_buildings)} buildings",
                "data": {"buildings": processed_buildings}
            }
            
        except Exception as e:
            self.logger.error(f"Error finishing all buildings for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Batch finish failed: {str(e)}",
                "data": {}
            }
    
    async def building_speedup(self):
        """건물 가속 - Redis에서 타이머 단축"""
        user_no = self.user_no
        
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            speedup_seconds = self.data.get('speedup_seconds', 0)
            
            if speedup_seconds <= 0:
                return {
                    "success": False,
                    "message": "Invalid speedup time",
                    "data": {}
                }
            
            # Redis에서 건물 정보 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            
            if not building or building['status'] != 2:
                return {
                    "success": False,
                    "message": "Building is not being upgraded",
                    "data": {}
                }
            
            # 타이머 단축
            end_time_str = building.get('end_time')
            if not end_time_str:
                return {"success": False, "message": "No end time found", "data": {}}
            
            current_end_time = datetime.fromisoformat(end_time_str)
            new_end_time = current_end_time - timedelta(seconds=speedup_seconds)
            
            # 현재 시간보다 이전이면 바로 완료 처리
            now = datetime.utcnow()
            if new_end_time <= now:
                new_end_time = now
            
            # Redis 업데이트
            building_redis = self.redis_manager.get_building_manager()
            updated_building = {
                **building,
                'end_time': new_end_time.isoformat()
            }
            
            await building_redis.update_cached_building(user_no, building_idx, updated_building)
            
            # 메모리 캐시 무효화
            self._cached_buildings = None
            
            self.logger.info(f"Building speedup (Redis): user={user_no}, building={building_idx}, speedup={speedup_seconds}s")
            
            return {
                "success": True,
                "message": f"Building {building_idx} accelerated by {speedup_seconds}s",
                "data": updated_building
            }
            
        except Exception as e:
            self.logger.error(f"Error speeding up building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Speedup failed: {str(e)}",
                "data": {}
            }
    
    async def building_cancel(self):
        """건물 건설/업그레이드 취소 - Redis만 업데이트 + 자원 환불"""
        user_no = self.user_no
        
        try:
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            refund_percent = self.data.get('refund_percent', 100)  # 기본 100% 환불
            
            if refund_percent < 0 or refund_percent > 100:
                return {
                    "success": False,
                    "message": "Invalid refund percent (0-100)",
                    "data": {}
                }
            
            # 1. Redis에서 건물 정보 조회
            buildings_data = await self.get_user_buildings()
            building = buildings_data.get(str(building_idx))
            
            if not building:
                return {
                    "success": False,
                    "message": f"Building {building_idx} not found",
                    "data": {}
                }
            
            status = building['status']
            
            # 2. 취소 가능한 상태 확인 (1: 건설 중, 2: 업그레이드 중)
            if status not in [1, 2]:
                return {
                    "success": False,
                    "message": "Building is not in progress (cannot cancel)",
                    "data": building
                }
            
            # 3. 환불할 자원 계산
            current_level = building['building_lv']
            target_level = building.get('target_level', current_level + 1)
            
            # 게임 설정 조회
            if self.CONFIG_TYPE not in GameDataManager.REQUIRE_CONFIGS:
                return {"success": False, "message": "Building configuration not found", "data": {}}
            
            if building_idx not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]:
                return {"success": False, "message": f"Building {building_idx} config not found", "data": {}}
            
            if target_level not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx]:
                return {"success": False, "message": f"Level {target_level} config not found", "data": {}}
            
            level_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx][target_level]
            costs = level_config.get('cost', {})
            
            if not costs:
                return {"success": False, "message": "Invalid building configuration", "data": {}}
            
            # 환불 금액 계산
            refund_resources = {}
            for resource_type, amount in costs.items():
                refund_amount = int(amount * refund_percent / 100)
                if refund_amount > 0:
                    refund_resources[resource_type] = refund_amount
            
            # 4. Redis 처리
            building_redis = self.redis_manager.get_building_manager()
            
            if status == 1:
                # 건설 중이면 Redis에서 삭제
                await building_redis.delete_cached_building(user_no, building_idx)
                action = "deleted"
            else:
                # 업그레이드 중이면 상태만 복구
                updated_building = {
                    **building,
                    'status': 0,
                    'start_time': None,
                    'end_time': None,
                    'target_level': None,
                    'last_dt': datetime.utcnow().isoformat()
                }
                await building_redis.update_cached_building(user_no, building_idx, updated_building)
                action = "restored"
            
            # 5. 자원 환불 (Redis)
            if refund_resources:
                resource_manager = ResourceManager(self.db_manager, self.redis_manager)
                for resource_type, amount in refund_resources.items():
                    await resource_manager.add_resource(user_no, resource_type, amount)
            
            # 메모리 캐시 무효화
            self._cached_buildings = None
            
            self.logger.info(f"Building cancel (Redis): user={user_no}, building={building_idx}, action={action}, refund={refund_resources}")
            
            return {
                "success": True,
                "message": f"Building {building_idx} cancelled and resources refunded",
                "data": {
                    "building_idx": building_idx,
                    "action": action,
                    "refund_resources": refund_resources,
                    "refund_percent": refund_percent
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error cancelling building for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Building cancel failed: {str(e)}",
                "data": {}
            }

    
    def _apply_building_buffs(self, user_no, base_time):
        """건설 시간 버프 적용"""
        try:
            if base_time <= 0:
                return base_time
            
            buff_manager = BuffManager(self.db_manager, self.redis_manager)
            building_speed_buffs = buff_manager.get_total_buffs_by_type(user_no, 'building_speed')
            
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
        
    def _get_mission_manager(self):
        from services.game.MissionManager import MissionManager
        return MissionManager(self.db_manager, self.redis_manager)
    
    def _get_resource_manager(self):
        from services.game.ResourceManager import ResourceManager
        return ResourceManager(self.db_manager, self.redis_manager)
    
    def _get_buff_manager(self):
        from services.game.BuffManager import BuffManager
        return BuffManager(self.db_manager, self.redis_manager)