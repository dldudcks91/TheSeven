# APIManager.py (비동기 버전)
from services.system import SystemManager, GameDataManager, LoginManager
from services.game import ResourceManager, BuildingManager, ResearchManager, UnitManager, BuffManager
from fastapi import HTTPException

class APIManager():
    
        
    api_map = {
        # === 시스템 API (1xxx) ===
        # (클래스, 메서드) 형식으로 튜플에 저장
        #1001: (GameDataManager, GameDataManager.get_all_configs),
        1002: (GameDataManager, GameDataManager.REQUIRE_CONFIGS),
        1010: (LoginManager, LoginManager.handle_user_login),
        1011: (ResourceManager, ResourceManager.resource_info),
        
        # === 건물 API (2xxx) ===
        2001: (BuildingManager, BuildingManager.building_info),
        2002: (BuildingManager, BuildingManager.building_create),
        2003: (BuildingManager, BuildingManager.building_levelup),
        2005: (BuildingManager, BuildingManager.building_cancel),
        
        # === 연구 API (3xxx) ===
        3001: (ResearchManager, ResearchManager.research_info),
        3002: (ResearchManager, ResearchManager.research_start),
        3003: (ResearchManager, ResearchManager.research_finish),
        3004: (ResearchManager, ResearchManager.research_cancel),
        
        # === 유닛 API (4xxx) ===
        4001: (UnitManager, UnitManager.unit_info),
        4002: (UnitManager, UnitManager.unit_train),
        4003: (UnitManager, UnitManager.unit_upgrade),
        #4004: (UnitManager, UnitManager.unit_finish),
    }
    
    def __init__(self, db_manager, redis_manager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        return
    
    async def process_request(self, user_no, api_code, data):
        """API 요청 처리 (비동기 버전)"""
        
        ServiceClass, method = self.api_map.get(api_code)
        
        if not method: 
            
            raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")
        
        if ServiceClass == GameDataManager:
            return method
        
        
        service_instance = ServiceClass(self.db_manager, self.redis_manager)
        
        service_instance.user_no = user_no
        service_instance.data = data
        
        
        return await method(service_instance)
        # 메서드가 비동기인지 확인하고 적절히 호출
        # if hasattr(method, '__call__'):
        #     import asyncio
        #     if asyncio.iscoroutinefunction(method):
        #         return await method()
        #     else:
        #         return method()
            
       
            
        
        return 
    
    