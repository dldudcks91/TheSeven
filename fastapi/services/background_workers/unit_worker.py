# =================================
# unit_worker.py (캐시 전용 버전)
# =================================
from .base_worker import BaseWorker
import asyncio
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session

class UnitProductionWorker(BaseWorker):
    """유닛 생산 완성 처리 워커 (캐시 전용)"""
    
    async def _process_completed_tasks(self):
        """완료된 유닛 생산들을 Redis 캐시에서만 처리"""
        try:
            unit_redis = self.redis_manager.get_unit_manager()
            completed_units = await unit_redis.get_completed_units()
            
            if not completed_units:
                return
            
            print(f"Processing {len(completed_units)} completed unit productions in cache")
            
            for completed_unit in completed_units:
                try:
                    await self._complete_task(completed_unit, None)
                except Exception as e:
                    print(f"Error completing unit task in cache: {e}")
                        
        except Exception as e:
            print(f"Error getting completed unit_training: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any], db: Session):
        """개별 유닛 생산 완성 처리 (Redis 캐시만 업데이트)"""
        user_no = completed_task['user_no']
        unit_idx = completed_task['unit_idx']
        task_id = completed_task['task_id']
        
        # 동시성 제어를 위한 락
        lock_key = f"unit_completion_lock:{user_no}:{task_id}"
        lock_set = await self.redis_manager.redis_client.set(
            lock_key, "1", nx=True, ex=30
        )
        if not lock_set:
            return
        
        try:
            # ✅ unit_manager의 비즈니스 로직 호출
            from managers.unit_manager import UnitManager
            
            unit_manager = UnitManager(self.redis_manager)
            
            result = await unit_manager.finish_unit_production(
                user_no=user_no,
                unit_idx=unit_idx,
                task_id=task_id
            )
            
            if result:
                print(f"Unit production completed in cache: "
                      f"user_no={user_no}, unit_idx={unit_idx}, "
                      f"quantity={result['quantity']}")
            
        except Exception as e:
            print(f"Error in _complete_task: {e}")
        finally:
            await self.redis_manager.redis_client.delete(lock_key)