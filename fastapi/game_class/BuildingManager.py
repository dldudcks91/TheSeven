#APIManager.py
from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from game_class import GameDataManager, ResourceManager


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
    ABALIABLE_BUILDINGS = [101, 201, 301, 401]
    
    #API 코드 상수 정의
    API_BUILDING_INFO = 2001
    API_BUILDING_CREATE = 2002
    API_BUILDING_UPGRADE = 2003
    API_BUILDING_FINISH = 2004     # 생산/업그레이드 완료
    API_BUILDING_CANCEL = 2005
    
    def __init__(self, user_no: int, api_code: int,  data: dict, db: Session):
        self.api_code = api_code
        self.user_no = user_no
        self.data = data
        self.db = db
        
        return
    
    def _validate_input(self):
        """공통 입력값 검증"""
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
        return {
            "id": building.id,
            "user_no": building.user_no,
            "building_idx": building.building_idx,
            "building_lv": building.building_lv,
            "status": building.status,
            "start_time": building.start_time.isoformat() if building.start_time else None,
            "end_time": building.end_time.isoformat() if building.end_time else None,
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
            return self.ABALIABLE_BUILDINGS
        
    def _handle_resource_transaction(self, user_no, building_idx, target_level):
        """자원 체크 및 소모를 한번에 처리"""
        required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][building_idx][target_level]
        costs = required['cost']
        upgrade_time = required['time']
        
        resource_manager = ResourceManager(self.db)
        if not resource_manager.check_require_resources(user_no, costs):
            return None, "Need More Food"
        
        resource_manager.consume_resources(user_no, costs)
        return upgrade_time, None
    
    
    def building_info(self):
        """
            api_code: 2001
            info: 건물 정보를 조회합니다.
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
            api_code: 2002
            info: 새 건물을 생성하고 DB에 저장합니다.
        """
        
        try:
            user_no = self.user_no
            building_idx = self.data.get('building_idx')
            
            
            #1. 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            #1-1.중복 체크
            building = self._get_building(user_no, building_idx)
            if building:
                return {"success": False, "message": "Building already exists", "data": {}}

            # 자원 처리
            upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, 1)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            #2-3. 시간
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(seconds = upgrade_time) 
            
            #3. 새 건물 생성
            building = models.Building(
                user_no=user_no, 
                building_idx=building_idx, 
                building_lv=0,
                status=1,
                start_time = start_time,
                end_time = end_time,
                last_dt = start_time
                
            )
            
            self.db.add(building)
            self.db.commit()
            self.db.refresh(building)
            result = { 
                "success": True,
                "message": f"Building create started. Will complete in {upgrade_time} seconds",
                "data": self._format_building_data(building)
            }
            return result 
            
        except Exception as e:
            self.db.rollback() 
            return {"success": False, "message": str(e)}
        
    
    
    def building_levelup(self):
        """
            api_code: 2003
            info: 건물 레벨을 업그레이드합니다.
        """
        try:
            user_no = self.user_no
            building_idx = self.data.get('building_idx')
            
            
            #1. 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            
            building = self._get_building(user_no, building_idx)
            
            #1-1. 건물 존재하는지 체크
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            #1-2.업그레이드 가능 상태 체크
            if building.status != 0: # 0이 아니면 이미 진행중인 작업이 있음
                return {"success": False, "message": "Building is already under construction or upgrade", "data": {}}
            
            #1-3.최대 레벨 체크
            if building.building_lv >= self.MAX_LEVEL:
                return {"success": False, "message": f"Building is already at maximum level ({self.MAX_LEVEL})", "data": {}}
            
            
            #2. 자원 및 시간 처리
            upgrade_time, error_msg = self._handle_resource_transaction(user_no, building_idx, building.building_lv +1)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(seconds = upgrade_time) 
            
            
            #3. 건물 업그레이드
            building.status = 2
            building.start_time = start_time
            building.end_time = end_time
            building.last_dt = start_time
                
            
            self.db.commit()
            self.db.refresh(building)
            
            return {
                "success": True,
                "message": f"Building {building_idx} upgrade started to {building.building_lv +1} lv. Will complete in {upgrade_time} seconds",
                "data": self._format_building_data(building)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error upgrading building: {str(e)}", "data": {}}
    
    def building_finish(self):
        """
            api_code: 2004 (추정)
            info: 건물 건설/업그레이드를 완료합니다.
        """
        try:
            user_no = self.user_no
            building_idx = self.data.get('building_idx')
            
            current_time = datetime.utcnow()
            
            # 건물 조회
            building = self._get_building(user_no, building_idx)
            
            if not building:
                return {"success": False, "message": "Building not found", "data": {}}
            
            # 건설/업그레이드 중인 상태가 아닌 경우
            if building.status not in [1, 2]:
                return {"success": False, "message": "Building is not under construction or upgrade", "data": {}}
            
            # 완료 시간이 아직 안된 경우
            if building.end_time and current_time < building.end_time:
                remaining_time = int((building.end_time - current_time).total_seconds())
                return {
                    "success": False, 
                    "message": f"Building is not ready yet. {remaining_time} seconds remaining", 
                    "data": {}
                }
            
            # 건설 완료 (status 1 -> 0, level 0 -> 1)
            if building.status == 1:
                building.building_lv = 1
                building.status = 0
                message = "Building construction completed"
            
            # 업그레이드 완료 (status 2 -> 0, level +1)
            elif building.status == 2:
                building.building_lv += 1
                building.status = 0
                message = f"Building upgraded to level {building.building_lv}"
            
            # 시간 정보 업데이트
            building.start_time = None
            building.end_time = None
            building.last_dt = current_time
            
            self.db.commit()
            self.db.refresh(building)
            
            return {
                "success": True,
                "message": message,
                "data": self._format_building_data(building)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error finishing building: {str(e)}", "data": {}}
    
    def active(self):
        
        """API 요청을 적절한 메서드로 라우팅합니다."""
        
        # 'user_no'는 __init__에서 이미 받았으므로, _validate_input에서는 'building_idx'만 확인하도록 수정
        # 'building_info'의 경우 'building_idx'가 필수가 아니므로 validation을 건너뜁니다.
        if self.api_code != self.API_BUILDING_INFO:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
        api_code = self.api_code
        if api_code == self.API_BUILDING_INFO:
            return self.building_info()
        
        elif api_code == self.API_BUILDING_CREATE:
            return self.building_create()
        
        elif api_code == self.API_BUILDING_UPGRADE: 
            return self.building_levelup()
        
        elif api_code == self.API_BUILDING_FINISH: 
            return self.building_finish()
        else:
            return {
                "success": False, 
                "message": f"Unknown API code: {api_code}", 
                "data": {}
            }