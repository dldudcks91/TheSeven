# =================================
# research_worker.py
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
    """연구 완성 처리 워커"""
    
    async def _process_completed_tasks(self):
        try:
            research_redis = self.redis_manager.get_research_manager()
            completed_researches = research_redis.get_completed_tasks()
            
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
            print(f"Error processing completed researches: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        user_no = completed_task['user_no']
        research_idx = int(completed_task['task_id'])
        
        lock_key = f"research_completion_lock:{user_no}:{research_idx}"
        if not self.redis_manager.redis_client.set(lock_key, "1", nx=True, ex=30):
            return
        
        try:
            research = db.query(models.UserResearch).filter(
                models.UserResearch.user_no == user_no,
                models.UserResearch.research_idx == research_idx
            ).first()
            
            if not research or research.status != 1:  # 연구 중 상태가 아님
                research_redis = self.redis_manager.get_research_manager()
                research_redis.remove_from_queue(user_no, research_idx)
                return
            
            # 연구 완성 처리
            research.status = 2  # 완료 상태
            research.completion_time = datetime.utcnow()
            research.end_time = None
            
            # Redis에서 제거
            research_redis = self.redis_manager.get_research_manager()
            research_redis.remove_from_queue(user_no, research_idx)
            
            print(f"Research completed: user_no={user_no}, research_idx={research_idx}")
            
        finally:
            self.redis_manager.redis_client.delete(lock_key)