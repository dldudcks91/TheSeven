# =================================
# worker_manager.py (비동기 버전)
# =================================
import asyncio
from typing import Dict, Any, Optional
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from .building_worker import BuildingCompletionWorker
from .unit_worker import UnitProductionWorker
from .research_worker import ResearchCompletionWorker
from .buff_worker import BuffExpirationWorker

class BackgroundWorkerManager:
    """모든 백그라운드 워커들을 통합 관리하는 클래스 (비동기 버전)"""
    
    def __init__(self):
        self.workers = {}
        self.worker_tasks = {}
        self.is_initialized = False
    
    async def initialize(self, redis_manager: RedisManager, db_manager: DBManager, config: Optional[Dict[str, int]] = None):
        """워커들 초기화"""
        if self.is_initialized:
            return
        
        # 기본 설정
        default_config = {
            'building_check_interval': 10,
            'unit_check_interval': 10,
            'research_check_interval': 10,
            'buff_check_interval': 10,
        }
        
        if config:
            default_config.update(config)
        
        # 각 워커 생성
        self.workers = {
            # 'building': BuildingCompletionWorker(
                
            #     redis_manager, 
            #     default_config['building_check_interval']
            # ),
            'unit': UnitProductionWorker(
                db_manager,
                redis_manager
            ),
            # 'research': ResearchCompletionWorker(
            #     redis_manager, 
            #     default_config['research_check_interval']
            # ),
            # 'buff': BuffExpirationWorker(
            #     redis_manager, 
            #     default_config['buff_check_interval']
            # )
        }
        
        self.is_initialized = True
        print("Background worker manager initialized")
    
    async def start_all_workers(self):
        """모든 워커 시작"""
        if not self.is_initialized:
            raise RuntimeError("Worker manager not initialized")
        
        for worker_name, worker in self.workers.items():
            if worker_name not in self.worker_tasks:
                task = asyncio.create_task(worker.start())
                self.worker_tasks[worker_name] = task
                print(f"Started {worker_name} worker")
        
        print(f"All {len(self.workers)} background workers started")
        return list(self.worker_tasks.values())
    
    async def start_worker(self, worker_name: str):
        """특정 워커만 시작"""
        if worker_name not in self.workers:
            raise ValueError(f"Unknown worker: {worker_name}")
        
        if worker_name not in self.worker_tasks:
            worker = self.workers[worker_name]
            task = asyncio.create_task(worker.start())
            self.worker_tasks[worker_name] = task
            print(f"Started {worker_name} worker")
            return task
    
    async def stop_all_workers(self):
        """모든 워커 중지"""
        for worker_name, worker in self.workers.items():
            await worker.stop()
            print(f"Stopped {worker_name} worker")
        
        # 모든 태스크 취소
        for worker_name, task in self.worker_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.worker_tasks.clear()
    
    async def stop_worker(self, worker_name: str):
        """특정 워커 중지"""
        if worker_name in self.workers:
            await self.workers[worker_name].stop()
            print(f"Stopped {worker_name} worker")
            
            # 해당 태스크 취소
            if worker_name in self.worker_tasks:
                task = self.worker_tasks[worker_name]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self.worker_tasks[worker_name]
    
    def get_all_worker_status(self) -> Dict[str, Any]:
        """모든 워커 상태 조회"""
        status = {
            'manager_initialized': self.is_initialized,
            'total_workers': len(self.workers),
            'workers': {}
        }
        
        for worker_name, worker in self.workers.items():
            worker_status = worker.get_worker_status()
            worker_status['task_running'] = worker_name in self.worker_tasks and not self.worker_tasks[worker_name].done()
            status['workers'][worker_name] = worker_status
        
        return status
    
    def get_worker_status(self, worker_name: str) -> Dict[str, Any]:
        """특정 워커 상태 조회"""
        if worker_name not in self.workers:
            return {'error': f'Worker {worker_name} not found'}
        
        worker_status = self.workers[worker_name].get_worker_status()
        worker_status['task_running'] = worker_name in self.worker_tasks and not self.worker_tasks[worker_name].done()
        return worker_status
    
    async def manual_process_all(self):
        """수동으로 모든 워커의 완료된 작업들 처리 (테스트/디버깅용)"""
        results = {}
        for worker_name, worker in self.workers.items():
            try:
                await worker._process_completed_tasks()
                results[worker_name] = "processed"
            except Exception as e:
                results[worker_name] = f"error: {str(e)}"
        
        return results
    
    async def manual_process_worker(self, worker_name: str):
        """특정 워커의 완료된 작업들 수동 처리"""
        if worker_name not in self.workers:
            return {'error': f'Worker {worker_name} not found'}
        
        try:
            await self.workers[worker_name]._process_completed_tasks()
            return {'status': 'processed'}
        except Exception as e:
            return {'error': str(e)}