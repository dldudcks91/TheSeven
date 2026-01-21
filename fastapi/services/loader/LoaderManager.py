import logging
import asyncio
from typing import List, Callable, Dict

# 로더 함수들 import
from services.alliance.alliance_loader import load_alliances_to_redis
# 나중에 추가될 로더들 예시:
# from services.item.item_loader import load_items_to_redis

logger = logging.getLogger(__name__)

class LoaderManager:
    """모든 데이터 로더를 통합 관리하는 클래스"""
    
    def __init__(self, db_manager, redis_manager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.loaders: List[Callable] = []
        self.load_results: Dict[str, int] = {}

    async def initialize(self):
        """
        사용할 모든 로더를 여기서 등록합니다.
        새로운 로더가 생기면 이 리스트에 추가만 하면 됩니다.
        """
        self.loaders = [
            load_alliances_to_redis,
            # load_items_to_redis,  <-- 나중에 추가될 로더들
            # load_rankings_to_redis,
        ]
        logger.info(f"LoaderManager initialized with {len(self.loaders)} loaders.")

    async def load_all(self) -> Dict[str, int]:
        """등록된 모든 로더를 순차적으로 실행"""
        print("🚀 [Loader] Starting data loading process...")
        
        for loader in self.loaders:
            loader_name = loader.__name__
            try:
                # 각 로더 실행
                count = await loader(self.db_manager, self.redis_manager)
                self.load_results[loader_name] = count
                print(f"✅ [Loader] {loader_name}: {count} records loaded")
            except Exception as e:
                logger.error(f"❌ [Loader] Error in {loader_name}: {e}")
                self.load_results[loader_name] = 0
                
        print(f"✨ [Loader] All loading finished. Results: {self.load_results}")
        return self.load_results