# =================================
# research_worker.py (비동기 버전)
# =================================
from .base_worker import BaseWorker
import models
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from services.redis_manager import RedisManager
from database import get_db

class ResearchCompletionWorker(BaseWorker):
    """연구 완성 처리 워커 (비동기 버전)"""
    
    async def _process_completed_tasks(self):
        try:
            research_redis = self.redis_manager.get_research_manager()
            completed_researches = await research_redis.get_completed_research()
            
            if not completed_researches:
                return
            
            print(f"Processing {len(completed_researches)} completed researches")
            
            for completed_research in completed_researches:
                db = None
                try:
                    db = self.get_db_session()
                    await self._complete_task(completed_research, db)
                    db.commit()
                except Exception as e:
                    if db:
                        db.rollback()
                    print(f"Error completing research task: {e}")
                finally:
                    if db:
                        db.close()
                        
        except Exception as e:
            print(f"Error getting completed research: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        user_no = completed_task['user_no']
        research_idx = int(completed_task['task_id'])
        
        lock_key = f"research_completion_lock:{user_no}:{research_idx}"
        lock_set = await self.redis_manager.redis_client.set(lock_key, "1", nx=True, ex=30)
        if not lock_set:
            return
        
        try:
            research = db.query(models.UserResearch).filter(
                models.UserResearch.user_no == user_no,
                models.UserResearch.research_idx == research_idx
            ).first()
            
            if not research or research.status != 1:  # 연구 중 상태가 아님
                research_redis = self.redis_manager.get_research_manager()
                await research_redis.remove_research(user_no, research_idx)
                return
            
            # 연구 완성 처리
            research.status = 2  # 완료 상태
            research.completion_time = datetime.utcnow()
            research.end_time = None
            
            # Redis에서 제거
            research_redis = self.redis_manager.get_research_manager()
            await research_redis.remove_research(user_no, research_idx)
            
            print(f"Research completed: user_no={user_no}, research_idx={research_idx}")
            
        finally:
            await self.redis_manager.redis_client.delete(lock_key)