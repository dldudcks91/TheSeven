from sqlalchemy.orm import Session
import models, schemas
from services.system import GameDataManager
from services.game import ResourceManager, BuffManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
import time
from datetime import datetime, timedelta

class BuildingManager():
    """건물 관리자 - 명시적 에러 처리 방식"""
    
    MAX_LEVEL = 10
    CONFIG_TYPE = 'building'
    AVAILABLE_BUILDINGS = [101, 201, 301, 401]
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None 
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_buildings = None
        
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
    
    def get_user_buildings(self):
        """사용자 건물 데이터를 캐시 우선으로 조회"""
        if self._cached_buildings is not None:
            return self._cached_buildings
        
        user_no = self.user_no
        
        # 1. Redis 캐시에서 먼저 조회
        building_redis = self.redis_manager.get_building_manager()
        self.cached_buildings = building_redis.get_cached_buildings(user_no)
        
        if self.cached_buildings:
            return self._cached_buildings
        
        # 2. 캐시 미스: DB에서 조회
        buildings_data = self._load_buildings_from_db(user_no)
        
        if buildings_data['success'] and buildings_data['data']:
            # 3. Redis에 캐싱
            building_redis.cache_user_buildings_data(user_no, buildings_data['data'])
            self._cached_buildings = buildings_data['data']
        else:
            self._cached_buildings = {}
            
        return self._cached_buildings
    
    def _format_building_for_cache(self, building_data):
        """캐시용 건물 데이터 포맷팅"""
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
    
    def _load_buildings_from_db(self, user_no):
        """DB에서 건물 데이터만 순수하게 조회"""
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
    
    def invalidate_user_building_cache(self, user_no: int):
        """사용자 건물 캐시 무효화"""
        building_redis = self.redis_manager.get_building_manager()
        return building_redis.invalidate_building_cache(user_no)
    
    def building_info(self):
        """건물 정보를 조회합니다 - 캐시 우선 접근"""
        buildings_data = self.get_user_buildings()
        
        return {
            "success": True,
            "message": f"Retrieved {len(buildings_data)} buildings",
            "data": buildings_data
        }
    
    def building_create(self):
        """새 건물을 생성하고 DB에 저장합니다."""
        user_no = self.user_no
        
        # 입력값 검증
        validation_error = self._validate_input()
        if validation_error:
            return validation_error
        
        building_idx = self.data.get('building_idx')
        
        # 중복 체크 (캐시된 데이터에서)
        buildings_data = self.get_user_buildings()
        existing_building = buildings_data.get(str(building_idx))
        if existing_building:
            return {"success": False, "message": "Building already exists", "data": {}}
        
        # 자원 처리
        base_upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, 1)
        if error_msg:
            return {"success": False, "message": error_msg, "data": {}}
        
        # 버프 적용된 시간 계산
        upgrade_time = self._apply_building_buffs(user_no, base_upgrade_time)
        
        # 시간 설정
        start_time = datetime.utcnow()
        completion_time = start_time + timedelta(seconds=upgrade_time) 
        
        # DBManager를 통한 새 건물 생성
        building_db = self.db_manager.get_building_manager()
        create_result = building_db.create_building(
            user_no=user_no,
            building_idx=building_idx,
            building_lv=0,
            status=1,
            start_time=start_time,
            end_time=completion_time,
            last_dt=start_time
        )
        
        if not create_result['success']:
            return create_result
        
        # Redis 완료 큐에 추가
        building_redis = self.redis_manager.get_building_manager()
        building_redis.add_building_to_queue(user_no, building_idx, completion_time)
        
        # 캐시 무효화
        self.invalidate_user_building_cache(user_no)
        
        return { 
            "success": True,
            "message": f"Building create started. Will complete in {upgrade_time} seconds",
            "data": create_result['data']
        }
    
    def building_levelup(self):
        """건물 레벨을 업그레이드합니다."""
        user_no = self.user_no
        
        # 입력값 검증
        validation_error = self._validate_input()
        if validation_error:
            return validation_error
        
        building_idx = self.data.get('building_idx')
        
        # 캐시된 데이터에서 건물 조회
        buildings_data = self.get_user_buildings()
        building = buildings_data.get(str(building_idx))
        if not building:
            return {"success": False, "message": "Building not found", "data": {}}
        
        if building['status'] != 0:
            return {"success": False, "message": "Building is already under construction or upgrade", "data": {}}
        
        if building['building_lv'] >= self.MAX_LEVEL:
            return {"success": False, "message": f"Building is already at maximum level ({self.MAX_LEVEL})", "data": {}}
        
        # 자원 및 시간 처리
        base_upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, building['building_lv'] + 1)
        if error_msg:
            return {"success": False, "message": error_msg, "data": {}}
        
        upgrade_time = self._apply_building_buffs(user_no, base_upgrade_time)
        
        start_time = datetime.utcnow()
        completion_time = start_time + timedelta(seconds=upgrade_time) 
        
        # DBManager를 통한 건물 업그레이드
        building_db = self.db_manager.get_building_manager()
        building_id = building.get('id') or building.get('building_idx')
        update_result = building_db.update(
            building_id,
            status=2,
            start_time=start_time,
            end_time=completion_time,
            last_dt=start_time
        )
        
        if not update_result['success']:
            return update_result
        
        # Redis 완료 큐에 추가
        building_redis = self.redis_manager.get_building_manager()
        building_redis.add_building_to_queue(user_no, building_idx, completion_time)
        
        # 캐시 무효화
        self.invalidate_user_building_cache(user_no)
        
        return {
            "success": True,
            "message": f"Building {building_idx} upgrade started to {building['building_lv'] + 1} lv. Will complete in {upgrade_time} seconds",
            "data": update_result['data']
        }
    
    def building_cancel(self):
        """건물 건설/업그레이드를 취소합니다."""
        user_no = self.user_no
        
        validation_error = self._validate_input()
        if validation_error:
            return validation_error
        
        building_idx = self.data.get('building_idx')
        
        # 캐시된 데이터에서 건물 조회
        buildings_data = self.get_user_buildings()
        building = buildings_data.get(str(building_idx))
        if not building:
            return {"success": False, "message": "Building not found", "data": {}}
        
        if building['status'] not in [1, 2]:
            return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
        
        # Redis 큐에서 제거
        building_redis = self.redis_manager.get_building_manager()
        building_redis.remove_building_from_queue(user_no, building_idx)
        
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
    
    def building_speedup(self):
        """건물 건설/업그레이드를 즉시 완료합니다."""
        user_no = self.user_no
        
        validation_error = self._validate_input()
        if validation_error:
            return validation_error
        
        building_idx = self.data.get('building_idx')
        
        # 캐시된 데이터에서 건물 조회
        buildings_data = self.get_user_buildings()
        building = buildings_data.get(str(building_idx))
        if not building:
            return {"success": False, "message": "Building not found", "data": {}}
        
        if building['status'] not in [1, 2]:
            return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
        
        # Redis에서 완료 시간 조회 및 업데이트
        building_redis = self.redis_manager.get_building_manager()
        completion_time = building_redis.get_building_completion_time(user_no, building_idx)
        if not completion_time:
            return {"success": False, "message": "Building completion time not found", "data": {}}
        
        # 즉시 완료를 위해 현재 시간으로 업데이트
        current_time = datetime.utcnow()
        update_success = building_redis.update_building_completion_time(user_no, building_idx, current_time)
        
        if not update_success:
            return {"success": False, "message": "Failed to update completion time", "data": {}}
        
        return {
            "success": True,
            "message": "Building completion time accelerated. Will complete shortly.",
            "data": building
        }
    
    def _handle_resource_transaction(self, user_no, building_idx, target_level):
        """자원 체크 및 소모를 한번에 처리"""
        # GameDataManager에서 설정 조회
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
        
        # 자원 체크 및 소모
        resource_manager = ResourceManager(self.db_manager)
        if not resource_manager.check_require_resources(user_no, costs):
            return None, "Need More Resources"
        
        consume_result = resource_manager.consume_resources(user_no, costs)
        if not consume_result:
            return None, "Failed to consume resources"
        
        return upgrade_time, None
    
    def _apply_building_buffs(self, user_no, base_time):
        """건설 시간 버프 적용"""
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
        return max(1, int(reduced_time))  # 최소 1초