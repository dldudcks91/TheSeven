from fastapi import FastAPI, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from schemas import ApiRequest
from game_class.Building import Building
app = FastAPI()


    

templates = Jinja2Templates(directory="templates")

api_dic = {
    2001: Building.buliding_info,
    2002: Building.buliding_create
    
    }

# templates 폴더의 "index.html" 응답
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    
    return templates.TemplateResponse("index.html", {"request": request})

# 사용자가 폼을 통해 보낸 데이터(content)를 받아서 "result.html" 템플릿에 넘김
@app.post("/api_post", response_class=HTMLResponse)
async def api_post(request: ApiRequest):
    
    api_code = request.api_code
    data = request.data
    user_no = data['user_no']
    print(api_code,user_no, data)
    result = {}
    return JSONResponse(content=result)