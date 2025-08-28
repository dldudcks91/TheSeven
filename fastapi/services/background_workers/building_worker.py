# =================================
# building_worker.py
# =================================
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from services.redis_manager import RedisManager
from database import get_db

from .base_worker import BaseWorker
import models

class BuildingCompletionWorker(BaseWorker):
    """건물 완성 처리 워커"""
    
    async def _process_completed_tasks(self):
        """완료된 건물들 처리"""
        try:
            building_redis = self.redis_manager.get_building_manager()
            completed_buildings = building_redis.get_completed_tasks()
            
            if not completed_buildings:
                return
            
            print(f"Processing {len(completed_buildings)} completed buildings")
            
            for completed_building in completed_buildings:
                db = None
                try:
                    db = self.get_db_session()
                    await self._complete_task(completed_building, db)
                    db.commit()
                except Exception as e:
                    if db:
                        db.rollback()
                    print(f"Error completing building task: {e}")
                finally:
                    if db:
                        db.close()
                        
        except Exception as e:
            print(f"Error processing completed buildings: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        """개별 건물 완성 처리"""
        user_no = completed_task['user_no']
        building_idx = int(completed_task['task_id'])
        
        # Redis 락으로 동시성 제어
        lock_key = f"building_completion_lock:{user_no}:{building_idx}"
        if not self.redis_manager.redis_client.set(lock_key, "1", nx=True, ex=30):
            return  # 다른 워커가 처리 중
        
        try:
            building = db.query(models.Building).filter(
                models.Building.user_no == user_no,
                models.Building.building_idx == building_idx
            ).first()
            
            if not building or building.status not in [1, 2]:
                # Redis에서 항목 제거
                building_redis = self.redis_manager.get_building_manager()
                building_redis.remove_building_from_queue(user_no, building_idx)
                return
            
            # 건물 완성 처리
            if building.status == 1:  # 건설 완료
                building.building_lv = 1
                action = "construction"
            elif building.status == 2:  # 업그레이드 완료
                building.building_lv += 1
                action = "upgrade"
            
            building.status = 0
            building.start_time = None
            building.end_time = None
            building.last_dt = datetime.utcnow()
            
            # Redis에서 제거
            building_redis = self.redis_manager.get_building_manager()
            building_redis.remove_building_from_queue(user_no, building_idx)
            
            print(f"Building {action} completed: user_no={user_no}, building_idx={building_idx}, level={building.building_lv}")
            
        finally:
            # 락 해제
            self.redis_manager.redis_client.delete(lock_key)