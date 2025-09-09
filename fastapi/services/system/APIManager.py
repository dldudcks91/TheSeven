#APIManager.py
from services.system import SystemManager, GameDataManager, LoginManager
from services.game import ResourceManager, BuildingManager, ResearchManager, UnitManager, BuffManager
from fastapi import HTTPException
class APIManager():
    
    service_dic = {
        1: SystemManager,
        2: BuildingManager,
        3: ResearchManager,
        4: UnitManager,
        }
    
    
    
    
    api_map = {
        # === 시스템 API (1xxx) ===
        1001: "get_all_configs",
        1002: "get_game_config",
        1010: "get_user_info",
        1011: "get_resource_info",
        
        
        # === 건물 API (2xxx) ===
        2001: "building_info",
        2002: "building_create", 
        2003: "building_levelup",
        #2004: "building_finish",
        2005: "building_cancel",
        
        # === 연구 API (3xxx) ===
        3001: "research_info",
        3002: "research_start",
        3003: "research_finish",
        3004: "research_cancel",
        
        # === 유닛 API (4xxx) ===
        4001: "unit_info",
        4002: "unit_train",
        4003: "unit_upgrade",
        4004: "unit_finish",
        
        
    }
    
        
    def __init__(self, db_manager, redis_manager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        return
    

        
    def process_request(self, user_no, api_code, data):
        api_code = api_code
        api_category = api_code // 1000
        
        
        #데이터 조회
        if api_category == 1:
            return self.process_info_request(user_no, api_code, data)
            
        #빌딩, 연구, 병사 등
        else: 
            
            method_name = self.api_map.get(api_code)
            ServiceClass = self.service_dic.get(api_category)
            if method_name and ServiceClass:
                
                
                    
                service_instance = ServiceClass(self.db_manager, self.redis_manager)
                
                service_instance.user_no = user_no
                service_instance.data = data
                    
                    
                method = getattr(service_instance, method_name)
                    
                return  method()
                
            else:
                raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")
            
        return 
        
    def process_info_request(self, user_no, api_code, data):
        
        if api_code == 1002:  # GAME_CONFIG_ALL
            return {"success": True, "message": "게임 설정 로드 성공", "data": GameDataManager.REQUIRE_CONFIGS}
        
        if api_code == 1010:
            
            login_manager = LoginManager(self.db_manager, self.redis_manager)
            return login_manager.handle_user_login(user_no)
        
        if api_code == 1011: # 자원 확인
            resource_manager = ResourceManager(self.db_manager)
            return resource_manager.resource_info(user_no)
        
        
        
        raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")