# workers/BackgroundWorkerManager.py
import asyncio
import logging
from typing import Dict, Any, Optional
from services.redis_manager import RedisManager
from .sync_worker import (
    BuildingSyncWorker,
    ResearchSyncWorker,
    UnitSyncWorker,
    ResourceSyncWorker,
    MissionSyncWorker
)

logger = logging.getLogger(__name__)


class BackgroundWorkerManager:
    """
    Redis → MySQL 동기화 워커들을 통합 관리
    
    각 워커는 dirty flag(sync_pending:{category}) 기반으로 동작하며,
    변경된 유저의 데이터만 주기적으로 MySQL에 동기화합니다.
    
    동기화 주기:
        - building:  10초 (변경 빈도 낮음, 유실 영향 높음)
        - research:  10초 (변경 빈도 낮음, 유실 영향 높음)
        - unit:      30초 (변경 빈도 중간, 유실 영향 높음)
        - resources: 60초 (변경 빈도 높음, 유실 영향 중간)
        - mission:  120초 (변경 빈도 낮음, 유실 영향 낮음)
    """
    
    def __init__(self):
        self.workers = {}
        self.worker_tasks = {}
        self.is_initialized = False
    
    async def initialize(self, redis_manager: RedisManager, config: Optional[Dict[str, float]] = None):
        """
        워커들 초기화
        
        Args:
            redis_manager: Redis 매니저
            config: 주기 설정 (선택사항)
                예: {'building_interval': 15, 'resources_interval': 30}
        """
        if self.is_initialized:
            return
        
        self.workers = {
            'building': BuildingSyncWorker(redis_manager),
            'research': ResearchSyncWorker(redis_manager),
            'unit': UnitSyncWorker(redis_manager),
            'resources': ResourceSyncWorker(redis_manager),
            'mission': MissionSyncWorker(redis_manager),
        }
        
        # 커스텀 주기 적용
        if config:
            interval_map = {
                'building_interval': 'building',
                'research_interval': 'research',
                'unit_interval': 'unit',
                'resources_interval': 'resources',
                'mission_interval': 'mission',
            }
            for config_key, worker_name in interval_map.items():
                if config_key in config and worker_name in self.workers:
                    self.workers[worker_name]._check_interval = config[config_key]
        
        self.is_initialized = True
        logger.info("BackgroundWorkerManager initialized")
    
    async def start_all_workers(self):
        """모든 워커 시작"""
        if not self.is_initialized:
            raise RuntimeError("Worker manager not initialized")
        
        for worker_name, worker in self.workers.items():
            if worker_name not in self.worker_tasks:
                task = asyncio.create_task(worker.start())
                self.worker_tasks[worker_name] = task
        
        logger.info(f"All {len(self.workers)} sync workers started")
    
    async def stop_all_workers(self):
        """
        모든 워커 중지 + 강제 동기화
        
        graceful shutdown 시 호출됨:
        1. 모든 워커 중지
        2. 남은 pending 데이터 강제 동기화
        """
        # 1. 강제 동기화 (pending에 남아있는 데이터 처리)
        logger.info("Force syncing all pending data before shutdown...")
        for worker_name, worker in self.workers.items():
            try:
                await worker.force_sync_all()
                logger.info(f"Force sync complete: {worker_name}")
            except Exception as e:
                logger.error(f"Force sync failed for {worker_name}: {e}")
        
        # 2. 워커 중지
        for worker_name, worker in self.workers.items():
            await worker.stop()
        
        # 3. 태스크 취소
        for worker_name, task in self.worker_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.worker_tasks.clear()
        logger.info("All sync workers stopped")
    
    async def start_worker(self, worker_name: str):
        """특정 워커만 시작"""
        if worker_name not in self.workers:
            raise ValueError(f"Unknown worker: {worker_name}")
        
        if worker_name not in self.worker_tasks:
            worker = self.workers[worker_name]
            task = asyncio.create_task(worker.start())
            self.worker_tasks[worker_name] = task
            logger.info(f"Started {worker_name} worker")
    
    async def stop_worker(self, worker_name: str):
        """특정 워커 중지"""
        if worker_name in self.workers:
            await self.workers[worker_name].stop()
            if worker_name in self.worker_tasks:
                task = self.worker_tasks[worker_name]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self.worker_tasks[worker_name]
            logger.info(f"Stopped {worker_name} worker")
    
    def get_all_worker_status(self) -> Dict[str, Any]:
        """모든 워커 상태 조회"""
        status = {
            'manager_initialized': self.is_initialized,
            'total_workers': len(self.workers),
            'workers': {}
        }
        
        for worker_name, worker in self.workers.items():
            worker_status = worker.get_worker_status()
            worker_status['task_running'] = (
                worker_name in self.worker_tasks 
                and not self.worker_tasks[worker_name].done()
            )
            status['workers'][worker_name] = worker_status
        
        return status
    
    def get_worker_status(self, worker_name: str) -> Dict[str, Any]:
        """특정 워커 상태 조회"""
        if worker_name not in self.workers:
            return {'error': f'Worker {worker_name} not found'}
        
        worker_status = self.workers[worker_name].get_worker_status()
        worker_status['task_running'] = (
            worker_name in self.worker_tasks 
            and not self.worker_tasks[worker_name].done()
        )
        return worker_status
