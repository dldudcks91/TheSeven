# APIManager.py (비동기 버전)
from services.system import SystemManager, LoginManager, GameDataManager, UserInitManager
#from services.system.GameDataManager import
#from services.system.UserInitManager import 
from services.game import ResourceManager, BuffManager, ItemManager, MissionManager, BuildingManager, ResearchManager, UnitManager, ShopManager, HeroManager, AllianceManager
from fastapi import HTTPException

class APIManager():
    
        
    api_map = {
        # === 시스템 API (1xxx) ===
        # (클래스, 메서드) 형식으로 튜플에 저장
        
        1002: (GameDataManager, GameDataManager.get_all_configs),
        1003: (UserInitManager, UserInitManager.create_new_user),
        1010: (LoginManager, LoginManager.handle_user_login),
        1011: (ResourceManager, ResourceManager.resource_info),
        1012: (BuffManager, BuffManager.buff_info),
        
        
        
        # === 건물 API (2xxx) ===
        2001: (BuildingManager, BuildingManager.building_info),
        2002: (BuildingManager, BuildingManager.building_create),
        2003: (BuildingManager, BuildingManager.building_upgrade),
        2004: (BuildingManager, BuildingManager.building_finish),
        2005: (BuildingManager, BuildingManager.building_cancel),
        2006: (BuildingManager, BuildingManager.finish_all_completed_buildings),
        
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
        
        # === 미션 API (5xxx) ===
        5001: (MissionManager, MissionManager.mission_info),
        5002: (MissionManager, MissionManager.mission_claim),

        # === 아이템 API (60xx) === 

        6001: (ItemManager, ItemManager.item_info),

        6011: (ShopManager, ShopManager.shop_info),
        6012: (ShopManager, ShopManager.shop_refresh),
        6013: (ShopManager, ShopManager.shop_buy),
        

        # === 연맹 API (70xx) ===
        7001: (AllianceManager, AllianceManager.alliance_info),
        7002: (AllianceManager, AllianceManager.alliance_create),
        7003: (AllianceManager, AllianceManager.alliance_join),
        7004: (AllianceManager, AllianceManager.alliance_leave),
        7005: (AllianceManager, AllianceManager.alliance_search),
        7006: (AllianceManager, AllianceManager.alliance_members),
        7007: (AllianceManager, AllianceManager.alliance_kick),
        7008: (AllianceManager, AllianceManager.alliance_promote),
        7009: (AllianceManager, AllianceManager.alliance_applications),
        7010: (AllianceManager, AllianceManager.alliance_approve),
        7011: (AllianceManager, AllianceManager.alliance_donate),
        7012: (AllianceManager, AllianceManager.alliance_set_join_type),
        7013: (AllianceManager, AllianceManager.alliance_disband),
    }
    
    def __init__(self, db_manager, redis_manager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        return
    
    async def process_request(self, user_no, api_code, data):
        """API 요청 처리 (비동기 버전)"""
        
        
        api = self.api_map.get(api_code)
        print(user_no, api_code, data, api)
        if api == None:
            print("process request:", user_no, api_code, data)
            raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")
        else:
            ServiceClass, method = api
        
            
            
        
        if ServiceClass == GameDataManager:
            service_instance = ServiceClass()
            
            return method()
        
        
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
    
    