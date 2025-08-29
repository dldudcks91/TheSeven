
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

import models, schemas
from services.system import GameDataManager
from services.game import ResourceManager
from services.redis_manager import RedisManager
from datetime import datetime, timedelta

'''
status 값
0: 비활성/완료
1: 활성
2: 만료됨

buff_type 값 (적용 대상)
0: 전체 (글로벌)
1: 연맹 (ally)
2: 개인 (personal)
'''

class BuffManager:
    CONFIG_TYPE = 'buff'
    
    # 버프 상태 상수
    STATUS_INACTIVE = 0
    STATUS_ACTIVE = 1
    STATUS_EXPIRED = 2
    
    # 버프 적용 대상 상수
    TARGET_GLOBAL = 0
    TARGET_ALLY = 1
    TARGET_PERSONAL = 2
    
    # 버프 카테고리 상수
    BUFF_CATEGORIES = {
        'building_speed': 'construction',
        'research_speed': 'research',
        'unit_train_speed': 'unit_training',
        'unit_upgrade_speed': 'unit_upgrade',
        'attack_boost': 'attack',
        'defense_boost': 'defense',
        'movement_speed': 'movement',
        'resource_production': 'production',
        'resource_gathering': 'gathering'
    }
    
    def __init__(self, db: Session, redis_manager: RedisManager = None):
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
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }
        
        buff_idx = self.data.get('buff_idx')
        if not buff_idx:
            return {
                "success": False,
                "message": f"Missing required fields: buff_idx: {buff_idx}",
                "data": {}
            }
        
        return None
    
    def _format_buff_data(self, buff):
        """버프 데이터를 응답 형태로 포맷팅"""
        # Redis에서 실제 완료 시간을 조회 (서버에서 관리하는 시간)
        redis_completion_time = None
        if buff.status == self.STATUS_ACTIVE:
            try:
                buff_redis = self.redis_manager.get_buff_manager()
                redis_completion_time = buff_redis.get_buff_completion_time(
                    buff.user_no, buff.buff_idx
                )
            except Exception as redis_error:
                print(f"Redis error: {redis_error}")
                redis_completion_time = None
        
        return {
            "id": buff.id,
            "user_no": buff.user_no,
            "ally_no": buff.ally_no,
            "buff_type": buff.buff_type,
            "target_no": buff.target_no,
            "buff_idx": buff.buff_idx,
            "status": buff.status,
            "start_time": buff.start_time.isoformat() if buff.start_time else None,
            "end_time": redis_completion_time.isoformat() if redis_completion_time else None,
            "last_dt": buff.last_dt.isoformat() if buff.last_dt else None
        }
    
    def _get_buff(self, user_no, buff_idx):
        """특정 버프 조회"""
        return self.db.query(models.Buff).filter(
            models.Buff.user_no == user_no,
            models.Buff.buff_idx == buff_idx
        ).first()
    
    def _get_user_buffs(self, user_no, ally_no=0):
        """사용자 관련 버프 조회 (개인 + 연맹 + 글로벌)"""
        return self.db.query(models.Buff).filter(
            or_(
                and_(models.Buff.buff_type == self.TARGET_GLOBAL),  # 글로벌 버프
                and_(models.Buff.buff_type == self.TARGET_ALLY, models.Buff.target_no == ally_no),  # 연맹 버프
                and_(models.Buff.buff_type == self.TARGET_PERSONAL, models.Buff.target_no == user_no)  # 개인 버프
            ),
            models.Buff.status == self.STATUS_ACTIVE
        ).all()
    
    def _get_all_user_buffs(self, user_no):
        """사용자의 모든 버프 조회 (활성/비활성 포함)"""
        return self.db.query(models.Buff).filter(
            models.Buff.user_no == user_no
        ).all()
    
    def _handle_resource_transaction(self, user_no, buff_idx):
        """버프 활성화를 위한 자원 체크 및 소모"""
        try:
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][buff_idx]
            costs = required.get('cost', {})
            duration = required.get('duration', 3600)  # 기본 1시간
            
            if costs:
                resource_manager = ResourceManager(self.db)
                if not resource_manager.check_require_resources(user_no, costs):
                    return None, "Need More Resources"
                
                resource_manager.consume_resources(user_no, costs)
            
            return duration, None
            
        except Exception as e:
            return None, f"Resource error: {str(e)}"
    
    def buff_info(self):
        """
        버프 정보를 조회합니다.
        """
        try:
            user_no = self.user_no
            
            # 사용자의 모든 버프 조회
            user_buffs = self._get_all_user_buffs(user_no)
            
            # 버프 데이터 구성
            buffs_data = {}
            for buff in user_buffs:
                buffs_data[buff.buff_idx] = self._format_buff_data(buff)
            
            return {
                "success": True,
                "message": f"Retrieved {len(buffs_data)} buffs info",
                "data": buffs_data
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error retrieving buffs info: {str(e)}", "data": {}}
    
    def buff_activate(self):
        """
        버프를 활성화합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            buff_idx = self.data.get('buff_idx')
            target_no = self.data.get('target_no', user_no)  # 기본값은 자신
            buff_type = self.data.get('buff_type', self.TARGET_PERSONAL)  # 기본값은 개인 버프
            ally_no = self.data.get('ally_no', 0)
            
            # 기존 활성 버프 체크
            existing_buff = self.db.query(models.Buff).filter(
                models.Buff.user_no == user_no,
                models.Buff.buff_idx == buff_idx,
                models.Buff.status == self.STATUS_ACTIVE
            ).first()
            
            if existing_buff:
                return {"success": False, "message": "Buff is already active", "data": {}}
            
            # 자원 처리
            duration, error_msg = self._handle_resource_transaction(user_no, buff_idx)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 시간 설정
            start_time = datetime.utcnow()
            completion_time = start_time + timedelta(seconds=duration)
            
            # 기존 비활성 버프가 있으면 재활성화, 없으면 새로 생성
            buff = self._get_buff(user_no, buff_idx)
            if buff:
                buff.status = self.STATUS_ACTIVE
                buff.start_time = start_time
                buff.end_time = None  # DB에는 저장하지 않음
                buff.last_dt = start_time
            else:
                buff = models.Buff(
                    user_no=user_no,
                    ally_no=ally_no,
                    buff_type=buff_type,
                    target_no=target_no,
                    buff_idx=buff_idx,
                    status=self.STATUS_ACTIVE,
                    start_time=start_time,
                    end_time=None,  # DB에는 저장하지 않음
                    last_dt=start_time
                )
                self.db.add(buff)
            
            self.db.commit()
            self.db.refresh(buff)
            
            # Redis 완료 큐에 추가
            if self.redis_manager:
                buff_redis = self.redis_manager.get_buff_manager()
                buff_redis.add_buff(user_no, buff_idx, completion_time, buff_type, target_no)
            
            buff_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(buff_idx, {})
            buff_name = buff_config.get('name', f'Buff_{buff_idx}')
            
            return {
                "success": True,
                "message": f"Buff {buff_name} activated for {duration} seconds",
                "data": self._format_buff_data(buff)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error activating buff: {str(e)}", "data": {}}
    
    def buff_cancel(self):
        """
        버프를 취소/비활성화합니다.
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            buff_idx = self.data.get('buff_idx')
            
            buff = self._get_buff(user_no, buff_idx)
            if not buff:
                return {"success": False, "message": "Buff not found", "data": {}}
            
            if buff.status != self.STATUS_ACTIVE:
                return {"success": False, "message": "Buff is not active", "data": {}}
            
            # Redis 큐에서 제거
            if self.redis_manager:
                buff_redis = self.redis_manager.get_buff_manager()
                buff_redis.remove_buff(user_no, buff_idx)
            
            # 버프 비활성화
            buff.status = self.STATUS_INACTIVE
            buff.end_time = None
            buff.last_dt = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(buff)
            
            return {
                "success": True,
                "message": "Buff cancelled",
                "data": self._format_buff_data(buff)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error cancelling buff: {str(e)}", "data": {}}
    
    def buff_speedup(self):
        """
        버프를 즉시 완료합니다. (아이템 사용)
        """
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            buff_idx = self.data.get('buff_idx')
            
            buff = self._get_buff(user_no, buff_idx)
            if not buff:
                return {"success": False, "message": "Buff not found", "data": {}}
            
            if buff.status != self.STATUS_ACTIVE:
                return {"success": False, "message": "Buff is not active", "data": {}}
            
            # Redis에서 완료 시간 조회
            if self.redis_manager:
                buff_redis = self.redis_manager.get_buff_manager()
                completion_time = buff_redis.get_buff_completion_time(user_no, buff_idx)
                if not completion_time:
                    return {"success": False, "message": "Buff completion time not found", "data": {}}
                
                # 즉시 완료를 위해 현재 시간으로 업데이트
                current_time = datetime.utcnow()
                buff_redis.update_buff_completion_time(user_no, buff_idx, current_time)
            
            return {
                "success": True,
                "message": "Buff completion time accelerated. Will complete shortly.",
                "data": self._format_buff_data(buff)
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error speeding up buff: {str(e)}", "data": {}}
    
    def get_active_buffs(self, user_no, buff_category=None, ally_no=0):
        """
        활성화된 버프 목록을 조회합니다.
        buff_category: 특정 카테고리의 버프만 조회 (예: 'building_speed')
        """
        try:
            # 사용자 관련 활성 버프 조회
            active_buffs = self._get_user_buffs(user_no, ally_no)
            
            # 현재 시간 기준으로 만료된 버프 필터링
            current_time = datetime.utcnow()
            valid_buffs = []
            
            for buff in active_buffs:
                # Redis에서 실제 완료 시간 확인
                if self.redis_manager:
                    completion_time = self.redis_manager.get_buff_completion_time(
                        buff.user_no, buff.buff_idx
                    )
                    if completion_time and current_time >= completion_time:
                        continue  # 만료된 버프 제외
                
                # 버프 설정 정보 가져오기
                buff_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(buff.buff_idx, {})
                
                # 카테고리 필터링
                if buff_category:
                    config_category = buff_config.get('category', '')
                    if config_category != buff_category:
                        continue
                
                buff_data = {
                    'buff_idx': buff.buff_idx,
                    'category': buff_config.get('category', ''),
                    'effect_type': buff_config.get('effect_type', ''),
                    'value': buff_config.get('value', 0),
                    'reduction_percent': buff_config.get('reduction_percent', 0),
                    'increase_percent': buff_config.get('increase_percent', 0),
                    'buff_type': buff.buff_type,
                    'target_no': buff.target_no
                }
                valid_buffs.append(buff_data)
            
            return valid_buffs
            
        except Exception as e:
            print(f"Error getting active buffs: {e}")
            return []
    
    def calculate_buffed_value(self, user_no, base_value, buff_category, ally_no=0):
        """
        기본값에 버프 효과를 적용한 최종값을 계산합니다.
        """
        try:
            active_buffs = self.get_active_buffs(user_no, buff_category, ally_no)
            
            if not active_buffs:
                return base_value
            
            total_increase = 0
            total_reduction = 0
            
            for buff in active_buffs:
                # 증가 버프
                if buff.get('increase_percent', 0) > 0:
                    total_increase += buff['increase_percent']
                
                # 감소 버프 (시간 단축 등)
                if buff.get('reduction_percent', 0) > 0:
                    total_reduction += buff['reduction_percent']
            
            # 증가 효과 적용
            if total_increase > 0:
                base_value = int(base_value * (1 + total_increase / 100))
            
            # 감소 효과 적용 (시간 단축 등)
            if total_reduction > 0:
                total_reduction = min(total_reduction, 90)  # 최대 90% 단축
                base_value = int(base_value * (1 - total_reduction / 100))
                base_value = max(1, base_value)  # 최소 1
            
            return base_value
            
        except Exception as e:
            print(f"Error calculating buffed value: {e}")
            return base_value
    
    def get_completion_status(self):
        """
        현재 진행 중인 버프들의 완료 상태를 조회합니다.
        """
        try:
            user_no = self.user_no
            
            # 활성화된 버프들 조회
            active_buffs = self.db.query(models.Buff).filter(
                models.Buff.user_no == user_no,
                models.Buff.status == self.STATUS_ACTIVE
            ).all()
            
            completion_info = []
            current_time = datetime.utcnow()
            
            for buff in active_buffs:
                if self.redis_manager:
                    redis_completion_time = self.redis_manager.get_buff_completion_time(
                        user_no, buff.buff_idx
                    )
                    
                    if redis_completion_time:
                        remaining_seconds = max(0, int((redis_completion_time - current_time).total_seconds()))
                        completion_info.append({
                            "buff_idx": buff.buff_idx,
                            "status": buff.status,
                            "completion_time": redis_completion_time.isoformat(),
                            "remaining_seconds": remaining_seconds,
                            "is_ready": remaining_seconds == 0
                        })
            
            return {
                "success": True,
                "message": f"Retrieved completion status for {len(completion_info)} buffs",
                "data": completion_info
            }
            
        except Exception as e:
            return {"success": False, "message": f"Error getting completion status: {str(e)}", "data": []}