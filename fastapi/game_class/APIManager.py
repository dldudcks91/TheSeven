#APIManager.py
from game_class import GameDataManager, BuildingManager, ResearchManager, UnitManager
from fastapi import HTTPException
class APIManager():
    
    api_dic = {
        
        2: BuildingManager,
        3: ResearchManager,
        4: UnitManager,
        
        }
    
    def __init__(self, db):
        self.db = db
        return
    
    
        
        
        
        
    def process_request(self, user_no, api_code, data):
        api_code = api_code
        api_category = api_code // 1000
        
        
        #메타데이터 불러오기
        if api_code == 1002:  # GAME_CONFIG_ALL
            return {"success": True, "message": "게임 설정 로드 성공", "data": GameDataManager.REQUIRE_CONFIGS}
        
        
        #빌딩, 연구, 병사 등
        ServiceClass = self.api_dic[api_category]
        if not ServiceClass:
            raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")
        service_instance = ServiceClass(user_no, api_code, data, self.db)
        
        result = service_instance.active()
        return result
        