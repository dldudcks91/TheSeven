

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["pages"])

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("main.html", {"request": request})

@router.get("/resource.html", response_class=HTMLResponse) 
async def get_resource(request: Request):
    return templates.TemplateResponse("resource.html", {"request": request})

@router.get("/mission.html")
async def get_mission(request: Request):
    return templates.TemplateResponse("mission.html", {"request": request})

@router.get("/building.html")
async def get_building(request: Request):
    return templates.TemplateResponse("building.html", {"request": request})

@router.get("/research.html")
async def get_research(request: Request):
    return templates.TemplateResponse("research.html", {"request": request})


@router.get("/unit.html")
async def get_unit(request: Request):
    return templates.TemplateResponse("unit.html", {"request": request})


@router.get("/item.html")
async def get_item(request: Request):
    return templates.TemplateResponse("item.html", {"request": request})

@router.get("/shop.html")
async def get_shop(request: Request):
    return templates.TemplateResponse("shop.html", {"request": request})

@router.get("/hero.html")
async def get_hero(request: Request):
    return templates.TemplateResponse("hero.html", {"request": request})
