# routers/game_data.py - FastAPI 라우터 통합
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from services.redis_manager import RedisManager
from services.unified_game_service import UnifiedGameService
from services.comprehensive_login_service import ComprehensiveLoginService
from main import app


router = APIRouter(prefix="/game", tags=["game_data"])

def get_redis_manager() -> RedisManager:
    
    return app.state.redis_manager

@router.post("/login")
async def comprehensive_login(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """통합 로그인 - 모든 게임 데이터 캐싱"""
    login_service = ComprehensiveLoginService(db, redis_manager)
    return login_service.handle_user_login(user_no)

@router.get("/data/{user_no}")
async def get_all_user_data(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """사용자의 모든 게임 데이터 조회"""
    game_service = UnifiedGameService(db, redis_manager)
    return game_service.get_all_user_data(user_no)

@router.get("/buildings/{user_no}")
async def get_buildings(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """건물 정보만 조회"""
    game_service = UnifiedGameService(db, redis_manager)
    return game_service.building_manager.building_info(user_no)

@router.get("/units/{user_no}")
async def get_units(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """유닛 정보만 조회"""
    game_service = UnifiedGameService(db, redis_manager)
    return game_service.unit_manager.unit_info(user_no)

@router.get("/research/{user_no}")
async def get_research(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """연구 정보만 조회"""
    game_service = UnifiedGameService(db, redis_manager)
    return game_service.research_manager.research_info(user_no)

@router.get("/resources/{user_no}")
async def get_resources(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """자원 정보만 조회"""
    game_service = UnifiedGameService(db, redis_manager)
    return game_service.resource_manager.resource_info(user_no)

# 캐시 관리 엔드포인트들
@router.delete("/cache/{user_no}")
async def invalidate_user_cache(
    user_no: int,
    data_type: str = None,  # 특정 타입만 삭제하려면 buildings, units, research, resources, buffs 중 하나
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """사용자 캐시 무효화"""
    from services.game_data_cache_manager import GameDataCacheManager
    cache_manager = GameDataCacheManager(redis_manager)
    
    if data_type:
        result = cache_manager.invalidate_user_cache(user_no, data_type)
        return {"success": result, "message": f"Invalidated {data_type} cache for user {user_no}"}
    else:
        result = cache_manager.invalidate_user_cache(user_no)
        return {"success": result, "message": f"Invalidated all cache for user {user_no}"}

@router.get("/cache/status/{user_no}")
async def get_cache_status(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """사용자 캐시 상태 확인"""
    game_service = UnifiedGameService(db, redis_manager)
    cache_status = game_service._get_cache_status(user_no)
    
    return {
        "user_no": user_no,
        "cache_status": cache_status,
        "total_cached_types": sum(1 for cached in cache_status.values() if cached)
    }

@router.post("/cache/warm/{user_no}")
async def warm_user_cache(
    user_no: int,
    db: Session = Depends(get_db),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """사용자 캐시 워밍"""
    game_service = UnifiedGameService(db, redis_manager)
    return game_service.warm_user_cache(user_no)