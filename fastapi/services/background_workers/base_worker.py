# =================================
# base_worker.py (비동기 버전)
# =================================
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from services.redis_manager import RedisManager
from database import get_db

class BaseWorker(ABC):
    """모든 백그라운드 워커의 기본 클래스 (비동기 버전)"""
    
    def __init__(self, redis_manager: RedisManager, check_interval: int = 10):
        self.redis_manager = redis_manager
        self.check_interval = check_interval
        self.is_running = False
        self.worker_name = self.__class__.__name__
        self._stop_event = asyncio.Event()
    
    async def start(self):
        """워커 시작"""
        self.is_running = True
        self._stop_event.clear()
        print(f"{self.worker_name} started. Check interval: {self.check_interval}s")
        
        try:
            while self.is_running and not self._stop_event.is_set():
                try:
                    await self._process_completed_tasks()
                    
                    # 인터럽트 가능한 대기
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
                        # stop_event가 설정되면 종료
                        break
                    except asyncio.TimeoutError:
                        # 타임아웃은 정상적인 동작
                        continue
                        
                except Exception as e:
                    print(f"Error in {self.worker_name}: {e}")
                    # 에러 발생 시에도 인터럽트 가능한 대기
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
                        break
                    except asyncio.TimeoutError:
                        continue
        except asyncio.CancelledError:
            print(f"{self.worker_name} was cancelled")
        finally:
            self.is_running = False
            print(f"{self.worker_name} loop ended")
    
    async def stop(self):
        """워커 중지"""
        self.is_running = False
        self._stop_event.set()
        print(f"{self.worker_name} stop requested")
    
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
            "current_time": datetime.utcnow().isoformat(),
            "stop_event_set": self._stop_event.is_set()
        }