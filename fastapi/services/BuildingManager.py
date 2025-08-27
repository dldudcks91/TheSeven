from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from services import GameDataManager, ResourceManager, BuffManager
from services.redis_manager import RedisManager
import time
from datetime import datetime, timedelta

'''
status 값
0: 정상 (업그레이드 가능)
1: 건설중   
2: 업그레이드중
'''
class BuildingManager():
    MAX_LEVEL = 10
    CONFIG_TYPE = 'building'
    AVAILABLE_BUILDINGS = [101, 201, 301, 401]
    
    def __init__(self, db: Session, redis_manager: RedisManager):
        self._user_no: int = None 
        self._data: dict = None
        self.db = db
        self.redis_manager = redis_manager
        
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
        # data가 설정되지 않았을 경우를 대비한 체크
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
    
    def _format_building_data(self, building):
        """건물 데이터를 응답 형태로 포맷팅"""
        # Redis에서 실제 완료 시간을 조회 (서버에서 관리하는 시간)
        redis_completion_time = None
        if building.status in [1, 2]:  # 건설/업그레이드 중인 경우
            try:
                building_redis = self.redis_manager.get_building_manager()
                redis_completion_time = building_redis.get_building_completion_time(
                    building.user_no, building.building_idx
                )
            except Exception as redis_error:
                print(f"Redis error: {redis_error}")
                redis_completion_time = building.end_time
        
        return {
            "id": building.id,
            "user_no": building.user_no,
            "building_idx": building.building_idx,
            "building_lv": building.building_lv,
            "status": building.status,
            "start_time": building.start_time.isoformat() if building.start_time else None,
            "end_time": redis_completion_time.isoformat() if redis_completion_time else None,
            "last_dt": building.last_dt.isoformat() if building.last_dt else None
        }
    
    def _get_building(self, user_no, building_idx):
        """건물 조회"""
        return self.db.query(models.Building).filter(
            models.Building.user_no == user_no,
            models.Building.building_idx == building_idx
        ).first()
    
    def _get_all_user_buildings(self, user_no):
        """사용자의 모든 건물 조회"""
        return self.db.query(models.Building).filter(
            models.Building.user_no == user_no
        ).all()
    
    def _get_available_buildings(self):
        """건설 가능한 모든 건물 목록 (게임 설정에서)"""
        try:
            return list(GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].keys())
        except:
            return self.AVAILABLE_BUILDINGS
        
    def _handle_resource_transaction(self, user_no, building_idx, target_level):
        """자원 체크 및 소모를 한번에 처리"""
        required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx][target_level]
        costs = required['cost']
        upgrade_time = required['time']
        
        resource_manager = ResourceManager(self.db)
        if not resource_manager.check_require_resources(user_no, costs):
            return None, "Need More Resources"
        
        resource_manager.consume_resources(user_no, costs)
        return upgrade_time, None
    
    def _apply_building_buffs(self, user_no, base_time):
        """건설 시간 버프 적용"""
        try:
            buff_manager = BuffManager(self.db, self.redis_manager)
            # 건설 속도 버프들을 조회하여 시간 단축 적용
            building_speed_buffs = buff_manager.get_active_buffs(user_no, 'building_speed')
            
            total_reduction = 0
            for buff in building_speed_buffs:
                total_reduction += buff.get('reduction_percent', 0)
            
            # 최대 90% 단축으로 제한
            total_reduction = min(total_reduction, 90)
            
            # 시간 단축 적용
            reduced_time = base_time * (1 - total_reduction / 100)
            return max(1, int(reduced_time))  # 최소 1초
            
        except Exception as e:
            print(f"Error applying building buffs: {e}")
            return base_time
    
    def building_info(self):
        """
        건물 정보를 조회합니다.
        """
        try:
            # 입력값 검증
            user_no = self.user_no
            
            # 건물 조회
            user_buildings = self._get_all_user_buildings(user_no)
            
            # 건물 데이터 구성
            buildings_data = {}
            
            # 기존 건물들 추가
            for building in user_buildings:
                buildings_data[building.building_idx] = self._format_building_data(building)
            
            return {
                "success": True,
                "message": f"Retrieved {len(buildings_data)} buildings info",
                "data": buildings_data
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving buildings info: {str(e)}", "data": {}}
    
    def building_create(self):
        """
        새 건물을 생성하고 DB에 저장합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 중복 체크
            building = self._get_building(user_no, building_idx)
            if building:
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
            
            # 새 건물 생성
            building = models.Building(
                user_no=user_no, 
                building_idx=building_idx, 
                building_lv=0,
                status=1,
                start_time=start_time,
                end_time=completion_time,  # Redis 없을 경우를 대비해 DB에도 저장
                last_dt=start_time
            )
            
            self.db.add(building)
            self.db.commit()
            self.db.refresh(building)
            
            # Redis 완료 큐에 추가
            building_redis = self.redis_manager.get_building_manager()
            building_redis.add_building(user_no, building_idx, completion_time)
            
            return { 
                "success": True,
                "message": f"Building create started. Will complete in {upgrade_time} seconds",
                "data": self._format_building_data(building)
            }
            
        except Exception as e:
            self.db.rollback() 
            return {"success": False, "message": str(e), "data": {}}
    
    def building_levelup(self):
        """
        건물 레벨을 업그레이드합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            building = self._get_building(user_no, building_idx)
            
            # 건물 존재하는지 체크
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            # 업그레이드 가능 상태 체크
            if building.status != 0: # 0이 아니면 이미 진행중인 작업이 있음
                return {"success": False, "message": "Building is already under construction or upgrade", "data": {}}
            
            # 최대 레벨 체크
            if building.building_lv >= self.MAX_LEVEL:
                return {"success": False, "message": f"Building is already at maximum level ({self.MAX_LEVEL})", "data": {}}
            
            # 자원 및 시간 처리
            base_upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, building.building_lv + 1)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 버프 적용된 시간 계산
            upgrade_time = self._apply_building_buffs(user_no, base_upgrade_time)
            
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=upgrade_time) 
            
            # 건물 업그레이드
            building.status = 2
            building.start_time = start_time
            building.end_time = completion_time  # Redis 없을 경우를 대비해 DB에도 저장
            building.last_dt = start_time
            
            self.db.commit()
            self.db.refresh(building)
            
            # Redis 완료 큐에 추가 (Redis 기능이 활성화된 경우에만)
            try:
                if hasattr(self.redis_manager, 'add_building_to_queue'):
                    self.redis_manager.add_building_to_queue(user_no, building_idx, completion_time)
                    # Redis 사용시에는 DB의 end_time을 None으로 설정
                    building.end_time = None
                    self.db.commit()
                else:
                    print(f"Redis building queue not available, using DB end_time fallback")
            except Exception as redis_error:
                print(f"Redis error: {redis_error}")
            
            return {
                "success": True,
                "message": f"Building {building_idx} upgrade started to {building.building_lv + 1} lv. Will complete in {upgrade_time} seconds",
                "data": self._format_building_data(building)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error upgrading building: {str(e)}", "data": {}}
    
    def building_cancel(self):
        """
        건물 건설/업그레이드를 취소합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            
            # 건물 조회
            building = self._get_building(user_no, building_idx)
            
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            # 건설/업그레이드 중인 상태가 아닌 경우
            if building.status not in [1, 2]:
                return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
            
            # Redis 큐에서 제거
            building_redis = self.redis_manager.get_building_manager()
            building_redis.remove_building(user_no, building_idx)
            
            # 취소 처리
            if building.status == 1:
                # 건설 취소 - 건물 삭제
                self.db.delete(building)
                message = "Building construction cancelled and removed"
                building_data = {}
            elif building.status == 2:
                # 업그레이드 취소 - 상태만 원복
                building.status = 0
                building.start_time = None
                building.end_time = None
                building.last_dt = datetime.utcnow()
                message = "Building upgrade cancelled"
                building_data = self._format_building_data(building)
            
            self.db.commit()
            
            return {
                "success": True,
                "message": message,
                "data": building_data
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error cancelling building: {str(e)}", "data": {}}
    
    def building_speedup(self):
        """
        건물 건설/업그레이드를 즉시 완료합니다. (아이템 사용)
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            building_idx = self.data.get('building_idx')
            building = self._get_building(user_no, building_idx)
            
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            # 건설/업그레이드 중인 상태가 아닌 경우
            if building.status not in [1, 2]:
                return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
            
            # Redis에서 완료 시간 조회 및 업데이트
            building_redis = self.redis_manager.get_building_manager()
            completion_time = building_redis.get_building_completion_time(user_no, building_idx)
            if not completion_time:
                return {"success": False, "message": "Building completion time not found", "data": {}}
            
            # 즉시 완료를 위해 현재 시간으로 업데이트
            current_time = datetime.utcnow()
            building_redis.update_building_completion_time(user_no, building_idx, current_time)
            
            return {
                "success": True,
                "message": "Building completion time accelerated. Will complete shortly.",
                "data": self._format_building_data(building)
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error speeding up building: {str(e)}", "data": {}}
    
    def get_completion_status(self):
        """
        현재 진행 중인 건물들의 완료 상태를 조회합니다.
        """
        try:
            user_no = self.user_no
            
            # 진행 중인 건물들 조회
            active_buildings = self.db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.status.in_([1, 2])
            ).all()
            
            completion_info = []
            current_time = datetime.utcnow()
            
            for building in active_buildings:
                building_redis = self.redis_manager.get_building_manager()
                redis_completion_time = building_redis.get_building_completion_time(
                    user_no, building.building_idx
                )
                if redis_completion_time:
                    remaining_seconds = max(0, int((redis_completion_time - current_time).total_seconds()))
                    completion_info.append({
                        "building_idx": building.building_idx,
                        "status": building.status,
                        "completion_time": redis_completion_time.isoformat(),
                        "remaining_seconds": remaining_seconds,
                        "is_ready": remaining_seconds == 0
                    })
            
            return {
                "success": True,
                "message": f"Retrieved completion status for {len(completion_info)} buildings",
                "data": completion_info
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error getting completion status: {str(e)}", "data": []}