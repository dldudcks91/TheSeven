import logging
import json
from datetime import datetime, timezone
from .base_worker import BaseWorker
from services.game.UnitManager import UnitManager
from services.game.BuildingManager import BuildingManager  # 예시: 나중을 위해
from services.db_manager import DBManager
from database import SessionLocal


class TaskWorker(BaseWorker):
    """
    게임 내 시간 완료 작업(Task) 처리 통합 워커
    - Redis의 Task Queue를 감시하여 완료 시간이 지난 항목들을 처리합니다.
    """
    
    def __init__(self, redis_manager, websocket_manager = None, check_interval: float = 1.0):
        # 작업 처리는 실시간성이 중요하므로 기본 주기를 1초로 설정합니다.
        super().__init__(category='game_task', check_interval=check_interval)
        self.redis_manager = redis_manager
        self.websocket_manager = websocket_manager

    def _create_db_session(self):
        return SessionLocal()

    async def _process_pending(self):
        """매 주기마다 등록된 모든 카테고리의 태스크를 순차적으로 처리합니다."""
        db_session = self._create_db_session()
        db_manager = DBManager(db_session)
        
        try:
            # 1. 유닛 태스크 처리
            
            await self._handle_unit_tasks(db_manager)
            
            # 2. 건물 태스크 처리 (추후 확장 시 추가)
            # await self._handle_building_tasks(db_manager)
            
            # 3. 연구 태스크 처리 (추후 확장 시 추가)
            # await self._handle_research_tasks(db_manager)
            
        except Exception as e:
            self.logger.error(f"[{self.category}] Error in TaskWorker loop: {e}", exc_info=True)
        finally:
            db_session.close()

    async def _handle_unit_tasks(self, db_manager):
        """완료된 유닛 훈련/업그레이드 태스크 처리"""
        try:
            unit_manager = UnitManager(db_manager, self.redis_manager)
            completed_tasks = await unit_manager.get_completed_units_for_worker()
            
            if not completed_tasks:
                return
            
            for task in completed_tasks:
                user_no = int(task.get('user_no'))
                task_id = task.get('task_id')
                sub_id = task.get('sub_id')
                    
                unit_manager.user_no = user_no
                unit_manager.data = {"unit_type": task_id, "unit_idx": sub_id}

                
                # finish_unit_internal이 캐시 갱신 및 DB 동기화 큐 삽입 처리
                #success = await unit_manager.finish_unit_internal(user_no, task_id)
                result = await unit_manager.unit_finish()
                
                if result and result.get('success'):
                    self.logger.info(f"Unit task {task_id} completed for user {user_no}")
                    await self._send_websocket_notification(user_no, 'unit_complete', result)
                    
        except Exception as e:
            self.logger.error(f"Error processing unit tasks: {e}")


    async def _send_websocket_notification(self, user_no: int, message_type:str, result: dict):
        """WebSocket으로 완료 알림 전송"""
        if not self.websocket_manager:
            return
        try:
            message = json.dumps({
                'type': message_type,
                'user_no': user_no,
                'data': result.get('data', {})
            })
            await self.websocket_manager.send_personal_message(message, user_no)
        except Exception as e:
            self.logger.error(f"Error sending WebSocket notification: {e}")

    # BaseWorker의 추상 메서드이지만 Task 방식에서는 사용하지 않으므로 비워둡니다.
    async def _get_pending_users(self): pass
    async def _remove_from_pending(self, user_no): pass
    async def _sync_user(self, user_no, db_session): pass