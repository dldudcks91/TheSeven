from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest

from sqlalchemy.orm import Session

import models, schemas, database
from game_class import GameDataManager,  ReSourcesManager, BuildingManager
app = FastAPI()


    

templates = Jinja2Templates(directory="templates")

api_dic = {
    2: BuildingManager,
    
    
    }

@app.on_event("startup")
async def startup_event():
    """서버 시작시 게임 데이터 로드"""
    print("🚀 Starting Game Server...")
    
    # 게임 데이터를 메모리에 로드 (한번만!)
    GameDataManager.initialize()
    
    print("✅ Game Server is ready!")


# templates 폴더의 "index.html" 응답
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    
    return templates.TemplateResponse("index.html", {"request": request})

# 사용자가 폼을 통해 보낸 데이터(content)를 받아서 "result.html" 템플릿에 넘김
@app.post("/api_post", response_class=HTMLResponse)
async def api_post(request: ApiRequest, db: Session = Depends(database.get_db)):
    
    api_code = request.api_code
    api_category = api_code // 1000
    
    data = request.data
    
    ServiceClass = api_dic[api_category]
    if not ServiceClass:
        raise HTTPException(status_code=400, detail="유효하지 않은 API 코드입니다.")
    service_instance = api_dic[api_category](api_code, data,db)
    
    result = service_instance.active()
    #print(result)
    return JSONResponse(content=result)

