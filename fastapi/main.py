from fastapi import FastAPI, Form, Request, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest
from sqlalchemy.orm import Session
import models, schemas, database

from services.system import APIManager, GameDataManager, WebsocketManager
from services.db_manager import DBManager 
from services.redis_manager import RedisManager
from services.background_workers import BackgroundWorkerManager

import redis
import json
import logging
from routers import pages

app = FastAPI()

# 전역 변수 선언
redis_client = None
redis_manager = None
websocket_manager = None
worker_manager = None

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Client 데이터 마운트
app.mount("/templates", StaticFiles(directory="templates"), name="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(pages.router)

@app.on_event("startup")
async def startup_event():
    """서버 시작시 게임 데이터 및 Redis 초기화"""
    global redis_client, redis_manager, websocket_manager, worker_manager
    
    try:
        print("🚀 Starting Game Server...")
        
        # 1. Redis 클라이언트 초기화
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
        
        # app.state에 저장
        app.state.redis_client = redis_client
        app.state.redis_manager = redis_manager
        
        # 워커 관리자 초기화 및 시작
        worker_manager = BackgroundWorkerManager()
        await worker_manager.initialize(redis_manager)
        await worker_manager.start_all_workers()
        print("✅ BackGround Worker managers initialized")
        
        # WebSocket 관리자 초기화
        websocket_manager = WebsocketManager() 
        app.state.websocket_manager = websocket_manager
        print("✅ Websocket managers initialized")
        
        # 2. 게임 데이터를 메모리에 로드 (한번만!)
        GameDataManager.initialize()
        print("✅ Game data loaded")
        
        print("✅ Game Server is ready!")
        
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise


def get_db_manager(db: Session = Depends(database.get_db)) -> DBManager:
    """DB 관리자를 반환하는 의존성 함수"""
    return DBManager(db)


def get_redis_manager() -> RedisManager:
    """Redis 관리자를 반환하는 의존성 함수"""
    if not hasattr(app.state, 'redis_manager') or app.state.redis_manager is None:
        logger.error("Redis manager is not available")
        raise HTTPException(status_code=503, detail="Redis service is not available")
    return app.state.redis_manager


def get_websocket_manager() -> WebsocketManager:
    """WebSocket 관리자를 반환하는 의존성 함수"""
    if not hasattr(app.state, 'websocket_manager') or app.state.websocket_manager is None:
        logger.error("WebSocket manager is not available")
        raise HTTPException(status_code=503, detail="WebSocket service is not available")
    return app.state.websocket_manager


@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료시 정리"""
    global redis_client, worker_manager
    
    try:
        print("🛑 Shutting down Game Server...")
        
        # BackGround Worker 정리
        if worker_manager:
            try:
                await worker_manager.stop_all_workers()
                print("✅ BackGround Worker closed")
            except Exception as e:
                logger.error(f"Error stopping background workers: {e}")
        
        # Redis 연결 정리
        if redis_client:
            try:
                redis_client.close()
                print("✅ Redis connections closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")
        
        print("✅ Game Server shutdown complete")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


@app.post("/api")
async def api_post(
    request: ApiRequest, 
    db_manager: DBManager = Depends(get_db_manager),
    redis_manager: RedisManager = Depends(get_redis_manager)
):
    """API 요청 처리"""
    
    api_manager = APIManager(db_manager, redis_manager)
    result = api_manager.process_request(request.user_no, request.api_code, request.data)
    return JSONResponse(content=result)
        
    


@app.websocket("/ws/{user_no}")
async def websocket_endpoint(websocket: WebSocket, user_no: int):
    """WebSocket 엔드포인트"""
    try:
        # WebSocket 관리자 가져오기
        ws_manager = app.state.websocket_manager
        if ws_manager is None:
            await websocket.close(code=1011, reason="WebSocket service not available")
            return
            
        await ws_manager.connect(websocket, user_no)
        logger.info(f"WebSocket connected for user {user_no}")
        
        try:
            while True:
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                    message_type = message.get('type')
                    
                    if message_type == 'ping':
                        await ws_manager.send_personal_message({
                            'type': 'pong',
                            'timestamp': message.get('timestamp')
                        }, user_no)
                    
                    elif message_type == 'heartbeat':
                        await ws_manager.send_personal_message({
                            'type': 'heartbeat_ack'
                        }, user_no)
                    
                    else:
                        logger.warning(f"Unknown message type: {message_type}")
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from user {user_no}: {e}")
                    await ws_manager.send_personal_message({
                        'type': 'error',
                        'message': 'Invalid JSON format'
                    }, user_no)
                    
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user {user_no}")
            ws_manager.disconnect(user_no)
            
    except Exception as e:
        logger.error(f"WebSocket error for user {user_no}: {e}")
        try:
            if ws_manager:
                ws_manager.disconnect(user_no)
        except:
            pass


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    try:
        # Redis 연결 상태 확인
        redis_status = "ok"
        if redis_client:
            try:
                redis_client.ping()
            except Exception:
                redis_status = "error"
        else:
            redis_status = "not_initialized"
        
        # 게임 데이터 로드 상태 확인
        game_data_status = "ok" if GameDataManager.is_initialized() else "not_loaded"
        
        return {
            "status": "ok",
            "services": {
                "redis": redis_status,
                "game_data": game_data_status,
                "websocket": "ok" if websocket_manager else "not_initialized",
                "background_worker": "ok" if worker_manager else "not_initialized"
            }
        }
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


# 개발용 루트 엔드포인트
@app.get("/")
async def root():
    """루트 페이지"""
    return {"message": "Game Server is running"}


# 예외 핸들러
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP 예외 핸들러"""
    logger.warning(f"HTTP exception: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """일반 예외 핸들러"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)