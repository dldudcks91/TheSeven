from fastapi import FastAPI, Form, Request, Depends, HTTPException 
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest
from sqlalchemy.orm import Session
import models, schemas, database
from services.APIManager import APIManager
from services import GameDataManager
from services.redis_manager import RedisManager
import redis
from routers import pages

app = FastAPI()

# 전역 변수로 Redis 관리자 저장
redis_manager = None

app.mount("/templates", StaticFiles(directory="templates"), name="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup_event():
    """서버 시작시 게임 데이터 및 Redis 초기화"""
    global redis_manager
    
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
        
        # RedisManager 초기화
        redis_manager = RedisManager(redis_client)
        print("✅ Redis managers initialized")
        
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

@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료시 정리"""
    global redis_manager
    
    print("🛑 Shutting down Game Server...")
    
    if redis_manager:
        # Redis 연결 정리 (필요시)
        print("✅ Redis connections closed")
    
    print("✅ Game Server shutdown complete")

def get_redis_manager() -> RedisManager:
    """Redis 관리자를 반환하는 의존성 함수"""
    if redis_manager is None:
        raise HTTPException(status_code=503, detail="Redis service is not available")
    return redis_manager

app.include_router(pages.router)

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