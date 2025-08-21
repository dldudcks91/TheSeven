from sqlalchemy.orm import Session
import models, schemas # 모델 및 스키마 파일 import
from services import GameDataManager, ResourceManager

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
    
    # API 코드 상수
    API_RESEARCH_INFO = 3000
    API_RESEARCH_START = 3001
    API_RESEARCH_FINISH = 3002
    API_RESEARCH_CANCEL = 3003
    
    # 상태 상수
    STATUS_NOT_STARTED = 0
    STATUS_RESEARCHING = 1
    STATUS_COMPLETED = 2
    
    def __init__(self, db: Session):
        self._api_code: int = None 
        self._user_no: int= None 
        self._data: dict = None
        self.db = db
        
    @property
    def api_code(self):
        """API 코드의 getter"""
        return self._api_code

    @api_code.setter
    def api_code(self, code: int):
        """API 코드의 setter. 정수형인지 확인"""
        if not isinstance(code, int):
            raise ValueError("api_code는 정수여야 합니다.")
        self._api_code = code

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
        research_idx = self.data.get('research_idx')
        
        # research_start, research_finish, research_cancel에만 research_idx가 필요합니다.
        if self.api_code in [self.API_RESEARCH_START, self.API_RESEARCH_FINISH, self.API_RESEARCH_CANCEL] and not research_idx:
            return {
                "success": False, 
                "message": "Missing required field: research_idx", 
                "data": {}
            }
        return None
    
    def _format_research_data(self, research):
        """연구 데이터를 응답 형태로 포맷팅"""
        remaining_time = 0
        if research.status == self.STATUS_RESEARCHING and research.end_time:
            remaining_time = max(0, int((research.end_time - datetime.utcnow()).total_seconds()))
            
        return {
            "id": research.id,
            "user_no": research.user_no,
            "research_idx": research.research_idx,
            "research_lv": research.research_lv,
            "status": research.status,
            "start_time": research.start_time.isoformat() if research.start_time else None,
            "end_time": research.end_time.isoformat() if research.end_time else None,
            "last_dt": research.last_dt.isoformat() if research.last_dt else None,
            "remaining_time": remaining_time
        }
    
    def _get_research(self, user_no, research_idx):
        """연구 조회"""
        return self.db.query(models.Research).filter(
            models.Research.user_no == user_no,
            models.Research.research_idx == research_idx
        ).first()
    
    def _get_all_user_researches(self, user_no):
        """유저의 모든 연구 조회"""
        return self.db.query(models.Research).filter(
            models.Research.user_no == user_no
        ).all()
        
    def _handle_resource_transaction(self, user_no, research_idx, target_level):
        """자원 체크 및 소모를 한번에 처리"""
        try:
            required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][research_idx][target_level]
            costs = required['cost']
            research_time = required['time']
            
            resource_manager = ResourceManager(self.db)
            if not resource_manager.check_require_resources(user_no, costs):
                return None, "Need More Resources"
            
            resource_manager.consume_resources(user_no, costs)
            return research_time, None
        except KeyError:
            return None, "Invalid research_idx or target_level in config"
        except Exception as e:
            return None, f"Resource transaction error: {str(e)}"
    
    def _check_research_prerequisites(self, user_no, research_idx):
        """선행 연구 조건 확인"""
        try:
            research_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][research_idx][1]
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
            research_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][research_idx][1]
            effects = research_config.get('effects', {})
            
            # 여기서 연구 완료에 따른 효과를 적용
            # 예: 건물 건설 가능, 유닛 생산 가능, 능력치 증가 등
            # 실제 구현은 게임 요구사항에 따라 달라집니다
            
            return True
        except Exception as e:
            print(f"Error applying research effects: {str(e)}")
            return False
            
    # API Methods
    def research_info(self):
        """
        api_code: 3000
        info: 유저의 모든 연구 상태를 반환합니다.
        """
        try:
            user_no = self.user_no
            user_researches = self._get_all_user_researches(user_no)
            
            researches_data = {}
            for research in user_researches:
                researches_data[research.research_idx] = self._format_research_data(research)
                
            return {
                "success": True,
                "message": "Retrieved research information successfully",
                "data": {"researches": researches_data}
            }
        except Exception as e:
            return {"success": False, "message": f"Error retrieving research info: {str(e)}", "data": {}}

    def research_start(self):
        """
        api_code: 3001
        info: 새 연구를 시작하고 DB에 저장합니다.
        """
        try:
            user_no = self.user_no
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
            user_no = self.user_no
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

    def research_cancel(self):
        """
        api_code: 3003
        info: 진행 중인 연구를 취소하고 자원을 환불합니다.
        """
        try:
            user_no = self.user_no
            research_idx = self.data.get('research_idx')

            research = self._get_research(user_no, research_idx)
            if not research or research.status != self.STATUS_RESEARCHING:
                return {"success": False, "message": "No research in progress to cancel", "data": {}}

            # 진행률에 따른 환불률 계산 (BuildingManager와 유사하게)
            total_duration = (research.end_time - research.start_time).total_seconds()
            elapsed_time = (datetime.utcnow() - research.start_time).total_seconds()
            progress = min(elapsed_time / total_duration, 1.0) if total_duration > 0 else 1.0
            refund_rate = max(0.3, 1.0 - (progress * 0.7)) # 30% ~ 100% 환불

            try:
                # 자원 환불
                required = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][research_idx][1]
                costs = required['cost']
                refund_costs = {resource: int(cost * refund_rate) for resource, cost in costs.items()}
                
                resource_manager = ResourceManager(self.db)
                resource_manager.add_resources(user_no, refund_costs)

            except Exception as refund_error:
                print(f"Research cancellation refund failed: {refund_error}")
                # 환불 실패 시에도 연구는 취소되어야 하므로 에러를 무시하고 진행

            # 연구 상태 초기화
            research.status = self.STATUS_NOT_STARTED
            research.start_time = None
            research.end_time = None
            research.last_dt = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(research)

            return {
                "success": True,
                "message": f"Research cancelled. ({int(refund_rate*100)}% resources refunded)",
                "data": self._format_research_data(research)
            }
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error cancelling research: {str(e)}", "data": {}}
            
    def check_and_complete_tasks(self, user_no=None):
        """
        백그라운드에서 완료된 연구를 처리합니다.
        """
        try:
            current_time = datetime.utcnow()
            
            query = self.db.query(models.Research).filter(
                models.Research.status == self.STATUS_RESEARCHING,
                models.Research.end_time <= current_time
            )
            
            if user_no:
                query = query.filter(models.Research.user_no == user_no)
            
            completed_researches = query.all()
            results = []
            
            for research in completed_researches:
                # 연구 완료
                research.research_lv = 1
                research.status = self.STATUS_COMPLETED
                research.start_time = None
                research.end_time = None
                research.last_dt = current_time
                
                # 연구 완료 효과 적용
                self._apply_research_effects(research.user_no, research.research_idx)
                
                results.append({
                    "research_idx": research.research_idx,
                    "research_lv": research.research_lv
                })
            
            if results:
                self.db.commit()
            
            return {
                "success": True,
                "message": f"Completed {len(results)} research tasks",
                "data": {"completed": results}
            }
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Error completing research tasks: {str(e)}", "data": {}}

    def active(self):
        """API 요청을 적절한 메서드로 라우팅합니다."""
        
        # 공통 입력값 검증
        validation_error = self._validate_input()
        if validation_error:
            return validation_error
        
        api_code = self.api_code
        if api_code == self.API_RESEARCH_INFO:
            return self.research_info()
        elif api_code == self.API_RESEARCH_START:
            return self.research_start()
        elif api_code == self.API_RESEARCH_FINISH:
            return self.research_finish()
        elif api_code == self.API_RESEARCH_CANCEL:
            return self.research_cancel()
        else:
            return {
                "success": False, 
                "message": f"Unknown API code: {api_code}", 
                "data": {}
            }