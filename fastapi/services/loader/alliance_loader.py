"""
Alliance Data Loader

서버 시작 시 DB에서 연맹 데이터를 Redis로 로드하는 함수

사용 방법:
    main.py 또는 app 시작 시 호출

    from services.alliance.alliance_loader import load_alliances_to_redis

    @app.on_event("startup")
    async def startup_event():
        # 기존 초기화 코드...
        
        # 연맹 데이터 로드
        await load_alliances_to_redis(db_manager, redis_manager)
"""

import logging

logger = logging.getLogger(__name__)


async def load_alliances_to_redis(db_manager, redis_manager) -> int:
    """
    서버 시작 시 DB에서 모든 연맹 데이터를 Redis로 로드
    
    Args:
        db_manager: DBManager 인스턴스
        redis_manager: RedisManager 인스턴스
        
    Returns:
        로드된 연맹 수
    """
    try:
        
        
        alliance_db = db_manager.get_alliance_db_manager()
        alliance_redis = redis_manager.get_alliance_manager()
        
        loaded_count = await alliance_db.load_all_to_redis(alliance_redis)
        
        logger.info(f"Alliance data loaded: {loaded_count} alliances")
        return loaded_count
        
    except Exception as e:
        logger.error(f"Failed to load alliance data: {e}")
        return 0