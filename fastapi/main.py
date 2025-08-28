from fastapi import FastAPI, Form, Request, Depends, HTTPException 
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest
from sqlalchemy.orm import Session
import models, schemas, database


from services import GameDataManager
from services.APIManager import APIManager
from services.redis_manager import RedisManager
from services.background_workers import BackgroundWorkerManager

import redis
from routers import pages

app = FastAPI()

# 전역 변수로 Redis 관리자 & BackGround Worker 저장
redis_manager = None
redis_client = None
worker_manager = None


#Client 데이터 마운트
app.mount("/templates", StaticFiles(directory="templates"), name="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(pages.router)

@app.on_event("startup")
async def startup_event():
    """서버 시작시 게임 데이터 및 Redis 초기화"""
    global redis_manager, redis_client
    
    print("🚀 Starting Game Server...")
    
    # 1. Redis 클라이언트 초기화
    try:
        redis_client = redis.Redis(
            host='localhost',  # Redis 서버 주소
            port=6379,         # Redis 포트
            db=0,              # 데이터베이스 번호
            decode_responses=True,  # 문자열 응답 자동 디코딩
            socket_connect_timeout=5,  # 연결 타임아웃
            socket_timeout=5,          # 소켓 타임아웃
        )
        
        # Redis 연결 테스트
        redis_client.ping()
        print("✅ Redis connection established")
        
        # RedisManager
        redis_manager = RedisManager(redis_client)
        
        print("✅ Redis managers initialized")
        
        
        app.state.redis_client = redis_client
        app.state.redis_manager = redis_manager
        
        # 워커 관리자 초기화 및 시작
        worker_manager = BackgroundWorkerManager()
        await worker_manager.initialize(redis_manager)
        await worker_manager.start_all_workers()
        print("✅ BackGround Worker managers initialized")
        
    except redis.ConnectionError:
        print("❌ Redis connection failed! Server will start but Redis features will be disabled.")
        redis_manager = None
    except Exception as e:
        print(f"❌ Redis initialization error: {e}")
        redis_manager = None
    
    # 2. 게임 데이터를 메모리에 로드 (한번만!)
    GameDataManager.initialize()
    print("✅ Game data loaded")
    
    print("✅ Game Server is ready!")
    
def get_redis_manager() -> RedisManager:
    """Redis 관리자를 반환하는 의존성 함수"""
    if redis_manager is None:
        raise HTTPException(status_code=503, detail="Redis service is not available")
    return app.state.redis_manager


@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료시 정리"""
    global redis_manager
    
    print("🛑 Shutting down Game Server...")
    
    # Redis 연결 정리 (필요시)
    if redis_client:
        redis_client.close()
        print("✅ Redis connections closed")
        
    worker_manager.stop_all_workers()
    print("✅ BackGround Worker closed")
    
    print("✅ Game Server shutdown complete")





# 사용자가 폼을 통해 보낸 데이터(content)를 받아서 "result.html" 템플릿에 넘김
@app.post("/api", response_class=HTMLResponse)
async def api_post(
    request: ApiRequest, 
    db: Session = Depends(database.get_db),
    redis_mgr: RedisManager = Depends(get_redis_manager)
):
    api_manager = APIManager(db, redis_mgr)  # RedisManager 전달
    
    result = api_manager.process_request(request.user_no, request.api_code, request.data)
    return JSONResponse(content=result)



