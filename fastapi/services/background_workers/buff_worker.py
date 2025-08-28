# =================================
# buff_worker.py
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
class BuffExpirationWorker(BaseWorker):
    """버프 만료 처리 워커"""
    
    async def _process_completed_tasks(self):
        try:
            buff_redis = self.redis_manager.get_buff_manager()
            expired_buffs = buff_redis.get_completed_tasks()
            
            if not expired_buffs:
                return
            
            print(f"Processing {len(expired_buffs)} expired buffs")
            
            for expired_buff in expired_buffs:
                db = None
                try:
                    db = self.get_db_session()
                    await self._complete_task(expired_buff, db)
                    db.commit()
                except Exception as e:
                    if db:
                        db.rollback()
                    print(f"Error processing expired buff: {e}")
                finally:
                    if db:
                        db.close()
                        
        except Exception as e:
            print(f"Error processing expired buffs: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        user_no = completed_task['user_no']
        buff_id = int(completed_task['task_id'])
        
        lock_key = f"buff_expiration_lock:{user_no}:{buff_id}"
        if not self.redis_manager.redis_client.set(lock_key, "1", nx=True, ex=30):
            return
        
        try:
            user_buff = db.query(models.UserBuff).filter(
                models.UserBuff.id == buff_id,
                models.UserBuff.user_no == user_no,
                models.UserBuff.is_active == True
            ).first()
            
            if not user_buff:
                buff_redis = self.redis_manager.get_buff_manager()
                buff_redis.remove_from_queue(user_no, buff_id)
                return
            
            # 버프 만료 처리
            user_buff.is_active = False
            user_buff.actual_end_time = datetime.utcnow()
            
            # Redis에서 제거
            buff_redis = self.redis_manager.get_buff_manager()
            buff_redis.remove_from_queue(user_no, buff_id)
            
            print(f"Buff expired: user_no={user_no}, buff_id={buff_id}")
            
        finally:
            self.redis_manager.redis_client.delete(lock_key)