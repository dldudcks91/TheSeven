# unit_worker.py (최종 버전)
from .base_worker import BaseWorker
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session
from services.game import UnitManager


class UnitProductionWorker(BaseWorker):
    """유닛 생산 완성 처리 워커 (캐시 전용)"""
    
    def __init__(self, db_manager, redis_manager):
        """
        초기화
        
        Args:
            db_manager: DB 매니저
            redis_manager: Redis 매니저
        """
        super().__init__(db_manager, redis_manager)
        
        # ✅ UnitManager 한 번만 생성 (재사용)
        self.unit_manager = UnitManager(db_manager=self.db_manager, redis_manager=self.redis_manager)
    
    async def _process_completed_tasks(self):
        """완료된 유닛 생산들을 Redis 캐시에서만 처리"""
        try:
            # ✅ self.unit_manager 사용
            completed_units = await self.unit_manager.get_completed_units_for_worker()
            
            if not completed_units:
                self.logger.debug("No completed units to process")
                return
            
            self.logger.info(f"Processing {len(completed_units)} completed unit productions")
            
            
            # print("-------completed_units-------")
            # print(completed_units)
            # print("-----------------------------")
            success_count = 0
            fail_count = 0
            
            for completed_unit in completed_units:
                
                try:
                    result = await self._complete_task(completed_unit)
                    
                    if result:
                        success_count += 1
                    else:
                        fail_count += 1
                        
                except Exception as e:
                    fail_count += 1
                    self.logger.error(f"Error completing unit task: {e}")
            
            self.logger.info(f"Unit completion results: success={success_count}, fail={fail_count}")
                        
        except Exception as e:
            self.logger.error(f"Error in _process_completed_tasks: {e}")
    
    async def _complete_task(self, completed_task: Dict[str, Any]) -> bool:
        """
        개별 유닛 생산 완성 처리 (Redis 캐시만 업데이트)
        
        Args:
            completed_task: 완료된 작업 정보
            
        Returns:
            성공 시 True, 실패 시 False
        """
        user_no = completed_task['user_no']
        task_id = completed_task['task_id']
        
        # 동시성 제어를 위한 락
        lock_key = f"unit_completion_lock:{user_no}:{task_id}"
        lock_set = await self.redis_manager.redis_client.set(lock_key, "1", nx=True, ex=30)
        
        if not lock_set:
            self.logger.warning(f"Task already being processed: {task_id}")
            return False
        
        try:
            # ✅ self.unit_manager 재사용
            result = await self.unit_manager.finish_unit_internal(user_no, task_id)
            
            if result:
                self.logger.info(f"Unit production completed")
                return True
            else:
                self.logger.warning(
                    f"Unit production completion failed: "
                    f"user_no={user_no}, task_id={task_id}"
                )
                return False
            
        except Exception as e:
            self.logger.error(f"Error in _complete_task: {e}")
            return False
            
        finally:
            # 락 해제
            await self.redis_manager.redis_client.delete(lock_key)