from fastapi import FastAPI, Form, Request, Depends, HTTPException 
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest

from sqlalchemy.orm import Session

import models, schemas, database
from game_class.APIManager import APIManager
from game_class import GameDataManager
app = FastAPI()


app.mount("/templates", StaticFiles(directory="templates"), name="templates")

templates = Jinja2Templates(directory="templates")



@app.on_event("startup")
async def startup_event():
    """서버 시작시 게임 데이터 로드"""
    print("🚀 Starting Game Server...")
    
    # 게임 데이터를 메모리에 로드 (한번만!)
    GameDataManager.initialize()
    
    print("✅ Game Server is ready!")


# templates 폴더의 "main.html" 응답
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    
    return templates.TemplateResponse("main.html", {"request": request})

@app.get("/building.html")
async def get_building(request: Request):
    return templates.TemplateResponse("building.html", {"request": request})

@app.get("/unit.html")
async def get_unit(request: Request):
    return templates.TemplateResponse("unit.html", {"request": request})

# 사용자가 폼을 통해 보낸 데이터(content)를 받아서 "result.html" 템플릿에 넘김
@app.post("/api", response_class=HTMLResponse)
async def api_post(request: ApiRequest, db: Session = Depends(database.get_db)):
    
    
    api_manager = APIManager(db)
    
    
    result = api_manager.process_request(request.user_no, request.api_code, request.data)
    return JSONResponse(content=result)

