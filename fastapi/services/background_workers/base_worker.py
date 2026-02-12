# workers/base_worker.py
import asyncio
import logging
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session


class BaseWorker(ABC):
    """
    백그라운드 워커 기본 클래스
    
    dirty flag(sync_pending:{category}) 기반으로 동작:
    1. sync_pending set에서 변경된 user_no 목록 가져옴
    2. 주기당 DB 세션 하나를 생성
    3. 해당 유저의 Redis 데이터를 읽어서 MySQL에 동기화 (유저 단위 commit)
    4. 성공하면 sync_pending에서 제거
    5. 주기 끝나면 세션 닫기
    """
    
    def __init__(self, category: str, check_interval: float = 10.0):
        self.category = category
        self.sync_key = f"sync_pending:{category}"
        self._check_interval = check_interval
        self.running = False
        self.logger = logging.getLogger(f"SyncWorker:{category}")
        
        # 통계
        self._sync_count = 0
        self._error_count = 0
    
    async def start(self):
        self.running = True
        self.logger.info(f"[{self.category}] sync worker started (interval: {self._check_interval}s)")
        
        try:
            while self.running:
                try:
                    await self._process_pending()
                except Exception as e:
                    self.logger.error(f"[{self.category}] error in sync loop: {e}", exc_info=True)
                
                await asyncio.sleep(self._check_interval)
                
        except asyncio.CancelledError:
            self.logger.info(f"[{self.category}] sync worker cancelled")
            raise
        finally:
            self.running = False
            self.logger.info(f"[{self.category}] sync worker stopped")
    
    async def stop(self):
        self.logger.info(f"[{self.category}] stopping sync worker...")
        self.running = False
    
    @abstractmethod
    async def _get_pending_users(self) -> set:
        pass
    
    @abstractmethod
    async def _remove_from_pending(self, user_no: int):
        pass
    
    @abstractmethod
    async def _sync_user(self, user_no: int, db_session: Session):
        """
        특정 유저의 Redis 데이터를 MySQL에 동기화
        
        Args:
            user_no: 동기화할 유저 번호
            db_session: 현재 주기의 공유 DB 세션
        """
        pass
    
    @abstractmethod
    def _create_db_session(self) -> Session:
        """DB 세션 생성 (하위 클래스에서 SessionLocal() 호출)"""
        pass
    
    async def _process_pending(self):
        """한 주기: 세션 하나로 모든 pending 유저 동기화"""
        pending_users = await self._get_pending_users()
        
        if not pending_users:
            return
        
        self.logger.info(f"[{self.category}] syncing {len(pending_users)} users")
        
        db_session = self._create_db_session()
        success = 0
        fail = 0
        
        try:
            for user_no_str in pending_users:
                user_no = int(user_no_str)
                try:
                    await self._sync_user(user_no, db_session)
                    db_session.commit()  # 유저 단위 commit
                    await self._remove_from_pending(user_no)
                    success += 1
                except Exception as e:
                    db_session.rollback()  # 실패한 유저만 rollback
                    fail += 1
                    self.logger.error(f"[{self.category}] sync failed for user {user_no}: {e}")
        finally:
            db_session.close()
        
        self._sync_count += success
        self._error_count += fail
        
        if success > 0 or fail > 0:
            self.logger.info(f"[{self.category}] sync complete: success={success}, fail={fail}")
    
    async def force_sync_all(self):
        """강제 전체 동기화 (graceful shutdown 시 사용)"""
        self.logger.info(f"[{self.category}] force syncing all pending users...")
        await self._process_pending()
    
    def get_worker_status(self) -> dict:
        return {
            'category': self.category,
            'running': self.running,
            'check_interval': self._check_interval,
            'total_synced': self._sync_count,
            'total_errors': self._error_count,
        }