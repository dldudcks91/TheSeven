
from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from game_class import GameDataManager, ResourceManager

import time
from datetime import datetime, timedelta

'''
status 값
0: 미시작
1: 연구중  
2: 완료
'''
class ResearchManager():
    MAX_LEVEL = 1
    CONFIG_TYPE = 'research'
    
    # 상태 상수
    STATUS_NOT_STARTED = 0
    STATUS_RESEARCHING = 1
    STATUS_COMPLETED = 2
    
    def __init__(self, api_code: int, data: dict, db: Session):
        self.api_code = api_code
        self.data = data
        self.db = db
        
        return
    
    def _validate_input(self):
        """공통 입력값 검증"""
        user_no = self.data.get('user_no')
        research_idx = self.data.get('research_idx')
        
        if not user_no or not research_idx:
            return {
                "success": False, 
                "message": f"Missing required fields: user_no: {user_no} or research_idx: {research_idx}", 
                "data": {}
            }
        return None
    
    def _format_research_data(self, research):
        """연구 데이터를 응답 형태로 포맷팅"""
        return {
            "id": research.id,
            "user_no": research.user_no,
            "research_idx": research.research_idx,
            "research_lv": research.research_lv,
            "status": research.status,
            "start_time": research.start_time.isoformat() if research.start_time else None,
            "end_time": research.end_time.isoformat() if research.end_time else None,
            "last_dt": research.last_dt.isoformat() if research.last_dt else None
        }
    
    def _get_research(self, user_no, research_idx):
        """연구 조회"""
        return self.db.query(models.Research).filter(
            models.Research.user_no == user_no,
            models.Research.research_idx == research_idx
        ).first()
    
    def _handle_resource_transaction(self, user_no, research_idx, target_level):
        """자원 체크 및 소모를 한번에 처리"""
        required = GameDataManager.require_configs[self.CONFIG_TYPE][research_idx][target_level]
        costs = required['cost']
        research_time = required['time']
        
        resource_manager = ResourceManager(self.db)
        if not resource_manager.check_require_resources(user_no, costs):
            return None, "Need More Resources"
        
        resource_manager.consume_resources(user_no, costs)
        return research_time, None
    
    def _check_research_prerequisites(self, user_no, research_idx):
        """선행 연구 조건 확인"""
        try:
            research_config = GameDataManager.require_configs[self.CONFIG_TYPE][research_idx][1]
            required_research = research_config.get('prerequisites', [])
            
            for prereq_idx in required_research:
                prereq = self._get_research(user_no, prereq_idx)
                if not prereq or prereq.status != self.STATUS_COMPLETED:
                    return False, f"Required research {prereq_idx} not completed"
            
            return True, None
        except KeyError:
            return False, f"Invalid research_idx: {research_idx}"
    
    def _apply_research_effects(self, user_no, research_idx):
        """연구 완료 시 효과 적용"""
        try:
            research_config = GameDataManager.require_configs[self.CONFIG_TYPE][research_idx][1]
            effects = research_config.get('effects', {})
            
            # 여기서 연구 완료에 따른 효과를 적용
            # 예: 건물 건설 가능, 유닛 생산 가능, 능력치 증가 등
            # 실제 구현은 게임 요구사항에 따라 달라집니다
            
            return True
        except Exception as e:
            print(f"Error applying research effects: {str(e)}")
            return False
    
    def research_start(self):
        """
           api_code: 3001
           info: 새 연구를 시작하고 DB에 저장합니다.
        """
        try:
            user_no = self.data.get('user_no')
            research_idx = self.data.get('research_idx')
            
            # 중복 체크
            research = self._get_research(user_no, research_idx)
            if research:
                if research.status == self.STATUS_COMPLETED:
                    return {"success": False, "message": "Research already completed", "data": {}}
                elif research.status == self.STATUS_RESEARCHING:
                    return {"success": False, "message": "Research already in progress", "data": {}}
            
            # 선행 연구 체크
            is_valid, error_msg = self._check_research_prerequisites(user_no, research_idx)
            if not is_valid:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 자원 처리
            research_time, error_msg = self._handle_resource_transaction(user_no, research_idx, 1)
            if error_msg:
                return {"success": False, "message": error_msg, "data": {}}
            
            # 시간 계산
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(seconds=research_time)
            
            # 새 연구 생성 또는 업데이트
            if research:
                # 기존 연구가 있다면 재시작
                research.status = self.STATUS_RESEARCHING
                research.start_time = start_time
                research.end_time = end_time
                research.last_dt = start_time
            else:
                # 새 연구 생성
                research = models.Research(
                    user_no=user_no,
                    research_idx=research_idx,
                    research_lv=0,
                    status=self.STATUS_RESEARCHING,
                    start_time=start_time,
                    end_time=end_time,
                    last_dt=start_time
                )
                self.db.add(research)
            
            self.db.commit()
            self.db.refresh(research)
            
            return {
                "success": True,
                "message": f"Research started. Will complete in {research_time} seconds",
                "data": self._format_research_data(research)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error starting research: {str(e)}", "data": {}}
    
    def research_finish(self):
        """
           api_code: 3002
           info: 연구를 완료합니다.
        """
        try:
            user_no = self.data.get('user_no')
            research_idx = self.data.get('research_idx')
            
            current_time = datetime.utcnow()
            
            # 연구 조회
            research = self._get_research(user_no, research_idx)
            
            if not research:
                return {"success": False, "message": "Research not found", "data": {}}
            
            # 연구중인 상태가 아닌 경우
            if research.status != self.STATUS_RESEARCHING:
                if research.status == self.STATUS_COMPLETED:
                    return {"success": False, "message": "Research already completed", "data": {}}
                else:
                    return {"success": False, "message": "Research is not in progress", "data": {}}
            
            # 완료 시간이 아직 안된 경우
            if research.end_time and current_time < research.end_time:
                remaining_time = int((research.end_time - current_time).total_seconds())
                return {
                    "success": False, 
                    "message": f"Research is not ready yet. {remaining_time} seconds remaining", 
                    "data": {}
                }
            
            # 연구 완료
            research.research_lv = 1
            research.status = self.STATUS_COMPLETED
            research.start_time = None
            research.end_time = None
            research.last_dt = current_time
            
            # 연구 완료 효과 적용
            self._apply_research_effects(user_no, research_idx)
            
            self.db.commit()
            self.db.refresh(research)
            
            return {
                "success": True,
                "message": f"Research {research_idx} completed successfully",
                "data": self._format_research_data(research)
            }
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error finishing research: {str(e)}", "data": {}}
    
    def active(self):
        """API 요청을 적절한 메서드로 라우팅합니다."""
        
        # 공통 입력값 검증
        validation_error = self._validate_input()
        if validation_error:
            return validation_error
       
        api_code = self.api_code
        if api_code == 3001:
            return self.research_start()
        elif api_code == 3002:
            return self.research_finish()
        else:
            return {
                "success": False, 
                "message": f"Unknown API code: {api_code}", 
                "data": {}
            }