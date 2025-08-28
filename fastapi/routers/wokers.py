from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import BackgroundWorkerManager
templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["admin/workers"])
worker_manager = BackgroundWorkerManager()

# 관리자 API 엔드포인트들
@router.get("/admin/workers/status")
async def get_all_worker_status():
    """모든 워커 상태 조회"""
    return worker_manager.get_all_worker_status()

@router.get("/admin/workers/{worker_name}/status")
async def get_worker_status(worker_name: str):
    """특정 워커 상태 조회"""
    return worker_manager.get_worker_status(worker_name)

@router.post("/admin/workers/process")
async def manual_process_all():
    """모든 워커 수동 실행"""
    return await worker_manager.manual_process_all()

@router.post("/admin/workers/{worker_name}/process")
async def manual_process_worker(worker_name: str):
    """특정 워커 수동 실행"""
    return await worker_manager.manual_process_worker(worker_name)

@router.post("/admin/workers/{worker_name}/stop")
async def stop_worker(worker_name: str):
    """특정 워커 중지"""
    worker_manager.stop_worker(worker_name)
    return {"message": f"{worker_name} worker stopped"}

@router.post("/admin/workers/{worker_name}/start")
async def start_worker(worker_name: str):
    """특정 워커 시작"""
    try:
        await worker_manager.start_worker(worker_name)
        return {"message": f"{worker_name} worker started"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))