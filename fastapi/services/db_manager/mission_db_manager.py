from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import models
import logging


class MissionDBManager:
    """미션 DB 관리자 - 완료 여부와 보상 수령 여부 저장"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    # ============================================
    # 동기화용 bulk upsert
    # ============================================
    
    def bulk_upsert_missions(self, user_no: int, missions_data: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Redis 미션 데이터를 MySQL에 bulk upsert
        
        Args:
            user_no: 유저 번호
            missions_data: {mission_idx: {current_value, target_value, is_completed, is_claimed}}
        
        Note:
            Redis에는 is_completed/is_claimed (bool)로 저장되어 있고,
            MySQL에는 completed_at/claimed_at (datetime)으로 저장됨.
            - is_completed=true → completed_at에 현재시간 기록 (이미 있으면 유지)
            - is_claimed=true → claimed_at에 현재시간 기록 (이미 있으면 유지)
        """
        try:
            existing = self.db.query(models.UserMission).filter(
                models.UserMission.user_no == user_no
            ).all()
            existing_map = {str(m.mission_idx): m for m in existing}
            
            now = datetime.utcnow()
            
            for mission_idx_str, data in missions_data.items():
                mission_idx = int(mission_idx_str)
                is_completed = data.get('is_completed', False)
                is_claimed = data.get('is_claimed', False)
                
                if mission_idx_str in existing_map:
                    m = existing_map[mission_idx_str]
                    # completed_at: 이미 있으면 유지, 새로 완료되면 now
                    if is_completed and not m.completed_at:
                        m.completed_at = now
                    # claimed_at: 이미 있으면 유지, 새로 수령하면 now
                    if is_claimed and not m.claimed_at:
                        m.claimed_at = now
                else:
                    # 완료되거나 수령된 미션만 INSERT (진행중인 미션은 MySQL에 넣을 필요 없음)
                    if is_completed or is_claimed:
                        new_mission = models.UserMission(
                            user_no=user_no,
                            mission_idx=mission_idx,
                            completed_at=now if is_completed else None,
                            claimed_at=now if is_claimed else None
                        )
                        self.db.add(new_mission)
            
            self.db.flush()
            
            return {
                "success": True,
                "message": f"Synced missions for user {user_no}",
                "data": {}
            }
            
        except SQLAlchemyError as e:
            self.logger.error(f"bulk_upsert_missions error: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    # ============================================
    # 기존 메서드들 (변경 없음)
    # ============================================
    
    def get_user_missions(self, user_no: int) -> Dict[str, Any]:
        try:
            query = self.db.query(models.UserMission).filter(models.UserMission.user_no == user_no)
            missions = query.all()
            result = {}
            for mission in missions:
                result[mission.mission_idx] = {
                    'completed_at': mission.completed_at.isoformat() if mission.completed_at else None,
                    'claimed_at': mission.claimed_at.isoformat() if mission.claimed_at else None
                }
            return {"success": True, "message": f"Retrieved {len(result)} missions", "data": result}
        except Exception as e:
            self.logger.error(f"Error getting user missions: {e}")
            return {"success": False, "message": f"Database error: {str(e)}", "data": {}}
    
    def update_mission(self, user_no: int, mission_idx: int, 
                      is_completed: bool = None, is_claimed: bool = None) -> Dict[str, Any]:
        try:
            self.logger.info(f"Mission updated: user_no={user_no}, mission_idx={mission_idx}, completed={is_completed}, claimed={is_claimed}")
            return {"success": True, "message": "Mission updated", "data": {}}
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error updating mission: {e}")
            return {"success": False, "message": f"Database error: {str(e)}", "data": {}}
    
    def complete_mission(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        return self.update_mission(user_no, mission_idx, is_completed=True, is_claimed=False)
    
    def claim_reward(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        return self.update_mission(user_no, mission_idx, is_claimed=True)
    
    def complete_and_claim(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        return self.update_mission(user_no, mission_idx, is_completed=True, is_claimed=True)
    
    def sync_batch(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            success_count = 0
            error_count = 0
            for item in items:
                result = self.update_mission(item['user_no'], item['mission_idx'], item.get('is_completed'), item.get('is_claimed'))
                if result['success']:
                    success_count += 1
                else:
                    error_count += 1
            return {"success": True, "message": f"Synced {success_count} missions, {error_count} errors", "data": {"success_count": success_count, "error_count": error_count}}
        except Exception as e:
            self.logger.error(f"Error in batch sync: {e}")
            return {"success": False, "message": f"Batch sync error: {str(e)}", "data": {"success_count": 0, "error_count": len(items)}}
    
    def is_mission_completed(self, user_no: int, mission_idx: int) -> bool:
        try:
            return False
        except Exception as e:
            self.logger.error(f"Error checking mission completion: {e}")
            return False
    
    def is_reward_claimed(self, user_no: int, mission_idx: int) -> bool:
        try:
            return False
        except Exception as e:
            self.logger.error(f"Error checking reward claim: {e}")
            return False
    
    def get_user_mission_stats(self, user_no: int) -> Dict[str, Any]:
        try:
            total_completed = 0
            total_claimed = 0
            return {"success": True, "message": "Mission stats retrieved", "data": {"total_completed": total_completed, "total_claimed": total_claimed}}
        except Exception as e:
            self.logger.error(f"Error getting mission stats: {e}")
            return {"success": False, "message": f"Database error: {str(e)}", "data": {}}
