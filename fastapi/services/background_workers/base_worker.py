# workers/base_worker.py
import asyncio
import logging
from abc import ABC, abstractmethod
from services.redis_manager import RedisManager
from services.db_manager import DBManager

class BaseWorker(ABC):
    """
    모든 백그라운드 워커의 기본 클래스
    
    자식 클래스는 _process_completed_tasks()를 구현해야 합니다.
    """
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        """
        Args:
            db_manager: 데이터베이스 관리자
            redis_manager: Redis 관리자
        """
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.running = False
        self.logger = logging.getLogger(self.__class__.__name__)
        self._check_interval = 1  # 기본 1초마다 체크
    
    async def start(self):
        """워커 시작"""
        self.running = True
        self.logger.info(f"{self.__class__.__name__} started")
        
        try:
            while self.running:
                try:
                    await self._process_completed_tasks()
                except Exception as e:
                    self.logger.error(f"Error in processing loop: {e}", exc_info=True)
                
                # 다음 체크까지 대기
                await asyncio.sleep(self._check_interval)
                
        except asyncio.CancelledError:
            self.logger.info(f"{self.__class__.__name__} cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Fatal error in {self.__class__.__name__}: {e}", exc_info=True)
        finally:
            self.running = False
            self.logger.info(f"{self.__class__.__name__} stopped")
    
    async def stop(self):
        """워커 중지"""
        self.logger.info(f"Stopping {self.__class__.__name__}...")
        self.running = False
    
    @abstractmethod
    async def _process_completed_tasks(self):
        """
        완료된 작업들을 처리하는 메서드 (하위 클래스에서 구현 필수)
        
        이 메서드는 주기적으로 호출되며, 완료된 작업을 확인하고 처리합니다.
        """
        pass
    
    def set_check_interval(self, seconds: float):
        """
        작업 체크 주기 설정
        
        Args:
            seconds: 체크 주기 (초)
        """
        self._check_interval = max(0.1, seconds)  # 최소 0.1초
        self.logger.info(f"Check interval set to {self._check_interval} seconds")