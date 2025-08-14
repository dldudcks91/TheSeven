#APIManager.py
from game_class import BuildingManager, ResearchManager
from fastapi import HTTPException
class APIManager():
    
    api_dic = {
        2: BuildingManager,
        3: ResearchManager
        
        }
    
    def __init__(self, db):
        self.db = db
        return
    
    def process_request(self, api_code, data):
        api_code = api_code
        api_category = api_code // 1000
        data = data
        
        ServiceClass = self.api_dic[api_category]
        
        if not ServiceClass:
            raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")
        service_instance = ServiceClass(api_code, data, self.db)
        
        result = service_instance.active()
        return result
        