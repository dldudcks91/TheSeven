# background_workers/
# ├── __init__.py
# ├── base_worker.py          # 공통 워커 기능
# ├── building_worker.py      # 건물 완성 처리
# ├── unit_worker.py          # 유닛 생산 완성 처리
# ├── research_worker.py      # 연구 완성 처리
# ├── buff_worker.py          # 버프 만료 처리
# └── worker_manager.py       # 모든 워커 통합 관리

# =================================
# base_worker.py
# =================================
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from services.redis_manager import RedisManager
from database import get_db

class BaseWorker(ABC):
    """모든 백그라운드 워커의 기본 클래스"""
    
    def __init__(self, redis_manager: RedisManager, check_interval: int = 10):
        self.redis_manager = redis_manager
        self.check_interval = check_interval
        self.is_running = False
        self.worker_name = self.__class__.__name__
    
    async def start(self):
        """워커 시작"""
        self.is_running = True
        print(f"{self.worker_name} started. Check interval: {self.check_interval}s")
        
        while self.is_running:
            try:
                await self._process_completed_tasks()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                print(f"Error in {self.worker_name}: {e}")
                await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """워커 중지"""
        self.is_running = False
        print(f"{self.worker_name} stopped")
    
    def get_db_session(self) -> Session:
        """새로운 DB 세션 생성"""
        return next(get_db())
    
    @abstractmethod
    async def _process_completed_tasks(self):
        """완료된 작업들 처리 (하위 클래스에서 구현)"""
        pass
    
    @abstractmethod
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        """개별 작업 완성 처리 (하위 클래스에서 구현)"""
        pass
    
    def get_worker_status(self) -> Dict[str, Any]:
        """워커 상태 조회"""
        return {
            "worker_name": self.worker_name,
            "is_running": self.is_running,
            "check_interval": self.check_interval,
            "current_time": datetime.utcnow().isoformat()
        }







