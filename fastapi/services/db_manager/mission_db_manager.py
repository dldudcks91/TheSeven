# mission_db_manager.py

from typing import Dict, Any, List
from sqlalchemy.orm import Session
from datetime import datetime
import models
import logging


class MissionDBManager:
    """미션 DB 관리자 - 완료 여부와 보상 수령 여부 저장"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_user_missions(self, user_no: int) -> Dict[str, Any]:
        """
        유저의 미션 이력 조회 (완료 + 보상 수령 정보)
        
        Returns:
            {
                "success": True,
                "data": {
                    101001: {"is_completed": True, "is_claimed": True, "completed_at": "2024-01-01T00:00:00"},
                    101002: {"is_completed": True, "is_claimed": False, "completed_at": "2024-01-02T00:00:00"}
                }
            }
        """
        try:
            # SQL 쿼리 예시
            # from models import UserMission
            # 
            # missions = self.db.query(UserMission).filter(
            #     UserMission.user_no == user_no
            # ).all()
            
            query = self.db.query(models.UserMission).filter(models.UserMission.user_no == user_no)
            # 더미 데이터
            missions = query.all()
            
            result = {}
            for mission in missions:
                result[mission.mission_idx] = {
                    'completed_at': mission.completed_at.isoformat() if mission.completed_at else None,
                    'claimed_at': mission.claimed_at.isoformat() if mission.claimed_at else None
                }
            
            return {
                "success": True,
                "message": f"Retrieved {len(result)} missions",
                "data": result
            }
            
        except Exception as e:
            self.logger.error(f"Error getting user missions: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    def update_mission(self, user_no: int, mission_idx: int, 
                      is_completed: bool = None, is_claimed: bool = None) -> Dict[str, Any]:
        """
        미션 상태 업데이트 (완료 또는 보상 수령)
        
        Args:
            user_no: 유저 번호
            mission_idx: 미션 인덱스
            is_completed: 완료 여부 (None이면 변경 안함)
            is_claimed: 보상 수령 여부 (None이면 변경 안함)
        """
        try:
            # SQL 쿼리 예시
            # from models import UserMission
            # 
            # # 기존 레코드 조회
            # mission = self.db.query(UserMission).filter(
            #     UserMission.user_no == user_no,
            #     UserMission.mission_idx == mission_idx
            # ).first()
            # 
            # if not mission:
            #     # 새로운 레코드 생성
            #     mission = UserMission(
            #         user_no=user_no,
            #         mission_idx=mission_idx,
            #         is_completed=False,
            #         is_claimed=False
            #     )
            #     self.db.add(mission)
            # 
            # # 상태 업데이트
            # if is_completed is not None:
            #     mission.is_completed = is_completed
            #     if is_completed and not mission.completed_at:
            #         mission.completed_at = datetime.utcnow()
            # 
            # if is_claimed is not None:
            #     mission.is_claimed = is_claimed
            #     if is_claimed and not mission.claimed_at:
            #         mission.claimed_at = datetime.utcnow()
            # 
            # self.db.commit()
            
            self.logger.info(
                f"Mission updated: user_no={user_no}, mission_idx={mission_idx}, "
                f"completed={is_completed}, claimed={is_claimed}"
            )
            
            return {
                "success": True,
                "message": "Mission updated",
                "data": {}
            }
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error updating mission: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    def complete_mission(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        """미션 완료 처리 (보상은 아직 수령 안함)"""
        return self.update_mission(user_no, mission_idx, is_completed=True, is_claimed=False)
    
    def claim_reward(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        """보상 수령 처리"""
        return self.update_mission(user_no, mission_idx, is_claimed=True)
    
    def complete_and_claim(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        """미션 완료 + 보상 수령 동시 처리"""
        return self.update_mission(user_no, mission_idx, is_completed=True, is_claimed=True)
    
    def sync_batch(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        배치 동기화 (Worker용)
        
        Args:
            items: [
                {
                    "user_no": 1,
                    "mission_idx": 101001,
                    "is_completed": True,
                    "is_claimed": True
                }
            ]
        """
        try:
            success_count = 0
            error_count = 0
            
            for item in items:
                result = self.update_mission(
                    item['user_no'],
                    item['mission_idx'],
                    item.get('is_completed'),
                    item.get('is_claimed')
                )
                if result['success']:
                    success_count += 1
                else:
                    error_count += 1
            
            return {
                "success": True,
                "message": f"Synced {success_count} missions, {error_count} errors",
                "data": {
                    "success_count": success_count,
                    "error_count": error_count
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in batch sync: {e}")
            return {
                "success": False,
                "message": f"Batch sync error: {str(e)}",
                "data": {
                    "success_count": 0,
                    "error_count": len(items)
                }
            }
    
    def is_mission_completed(self, user_no: int, mission_idx: int) -> bool:
        """특정 미션 완료 여부 확인"""
        try:
            # SQL 쿼리 예시
            # from models import UserMission
            # 
            # mission = self.db.query(UserMission).filter(
            #     UserMission.user_no == user_no,
            #     UserMission.mission_idx == mission_idx
            # ).first()
            # 
            # return mission.is_completed if mission else False
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking mission completion: {e}")
            return False
    
    def is_reward_claimed(self, user_no: int, mission_idx: int) -> bool:
        """특정 미션 보상 수령 여부 확인"""
        try:
            # SQL 쿼리 예시
            # from models import UserMission
            # 
            # mission = self.db.query(UserMission).filter(
            #     UserMission.user_no == user_no,
            #     UserMission.mission_idx == mission_idx
            # ).first()
            # 
            # return mission.is_claimed if mission else False
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking reward claim: {e}")
            return False
    
    def get_user_mission_stats(self, user_no: int) -> Dict[str, Any]:
        """유저 미션 통계 조회"""
        try:
            # SQL 쿼리 예시
            # from models import UserMission
            # 
            # total_completed = self.db.query(UserMission).filter(
            #     UserMission.user_no == user_no,
            #     UserMission.is_completed == True
            # ).count()
            # 
            # total_claimed = self.db.query(UserMission).filter(
            #     UserMission.user_no == user_no,
            #     UserMission.is_claimed == True
            # ).count()
            
            total_completed = 0
            total_claimed = 0
            
            return {
                "success": True,
                "message": "Mission stats retrieved",
                "data": {
                    "total_completed": total_completed,
                    "total_claimed": total_claimed
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mission stats: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }