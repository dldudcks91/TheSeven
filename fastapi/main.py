from fastapi import FastAPI, Form, Request, Depends, HTTPException 
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest

from sqlalchemy.orm import Session

import models, schemas, database
from services.APIManager import APIManager
from services import GameDataManager

from routers import pages


app = FastAPI()


app.mount("/templates", StaticFiles(directory="templates"), name="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")



@app.on_event("startup")
async def startup_event():
    """서버 시작시 게임 데이터 로드"""
    print("🚀 Starting Game Server...")
    
    # 게임 데이터를 메모리에 로드 (한번만!)
    GameDataManager.initialize()
    
    print("✅ Game Server is ready!")



app.include_router(pages.router)


# 사용자가 폼을 통해 보낸 데이터(content)를 받아서 "result.html" 템플릿에 넘김
@app.post("/api", response_class=HTMLResponse)
async def api_post(request: ApiRequest, db: Session = Depends(database.get_db)):
    
    
    api_manager = APIManager(db)
    
    
    result = api_manager.process_request(request.user_no, request.api_code, request.data)
    return JSONResponse(content=result)

