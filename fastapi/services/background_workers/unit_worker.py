# =================================
# unit_worker.py
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
class UnitProductionWorker(BaseWorker):
    """유닛 생산 완성 처리 워커"""
    
    async def _process_completed_tasks(self):
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            completed_units = unit_redis.get_completed_tasks()
            
            if not completed_units:
                return
            
            print(f"Processing {len(completed_units)} completed unit productions")
            
            for completed_unit in completed_units:
                db = None
                try:
                    db = self.get_db_session()
                    await self._complete_task(completed_unit, db)
                    db.commit()
                except Exception as e:
                    if db:
                        db.rollback()
                    print(f"Error completing unit task: {e}")
                finally:
                    if db:
                        db.close()
                        
        except Exception as e:
            print(f"Error processing completed units: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        user_no = completed_task['user_no']
        unit_idx = int(completed_task['task_id'])
        queue_slot = int(completed_task.get('sub_id', 0))  # 생산 큐 슬롯
        
        lock_key = f"unit_completion_lock:{user_no}:{unit_idx}:{queue_slot}"
        if not self.redis_manager.redis_client.set(lock_key, "1", nx=True, ex=30):
            return
        
        try:
            # 유닛 생산 큐에서 해당 항목 조회
            unit_queue = db.query(models.UnitProductionQueue).filter(
                models.UnitProductionQueue.user_no == user_no,
                models.UnitProductionQueue.unit_idx == unit_idx,
                models.UnitProductionQueue.queue_slot == queue_slot,
                models.UnitProductionQueue.status == 1  # 생산 중
            ).first()
            
            if not unit_queue:
                unit_redis = self.redis_manager.get_unit_manager()
                unit_redis.remove_from_queue(user_no, unit_idx, queue_slot)
                return
            
            # 사용자 유닛 인벤토리에 추가
            user_unit = db.query(models.UserUnit).filter(
                models.UserUnit.user_no == user_no,
                models.UserUnit.unit_idx == unit_idx
            ).first()
            
            if user_unit:
                user_unit.quantity += unit_queue.quantity
            else:
                user_unit = models.UserUnit(
                    user_no=user_no,
                    unit_idx=unit_idx,
                    quantity=unit_queue.quantity
                )
                db.add(user_unit)
            
            # 생산 큐에서 제거
            db.delete(unit_queue)
            
            # Redis에서 제거
            unit_redis = self.redis_manager.get_unit_manager()
            unit_redis.remove_from_queue(user_no, unit_idx, queue_slot)
            
            print(f"Unit production completed: user_no={user_no}, unit_idx={unit_idx}, quantity={unit_queue.quantity}")
            
        finally:
            self.redis_manager.redis_client.delete(lock_key)