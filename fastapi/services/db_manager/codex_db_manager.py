# codex_db_manager.py

from typing import Dict, Any, List
from sqlalchemy.orm import Session
from datetime import datetime
import logging


class CodexDBManager:
    """도감 DB 관리자"""
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_codex(self, user_no: int) -> Dict[str, Any]:
        """DB에서 전체 도감 조회"""
        try:
            # SQL 쿼리 예시 (실제 모델에 맞게 수정)
            # from models import Codex
            # 
            # items = self.db.query(Codex).filter(
            #     Codex.user_no == user_no
            # ).all()
            
            # 더미 데이터
            items = []
            
            result = []
            for item in items:
                result.append({
                    'item_type': item.item_type,
                    'item_id': item.item_id,
                    'completed_at': item.completed_at.isoformat() if item.completed_at else '',
                    'extra_data': item.extra_data or {}  # JSON 필드
                })
            
            return {
                "success": True,
                "message": f"Retrieved {len(result)} codex items",
                "data": result
            }
            
        except Exception as e:
            self.logger.error(f"Error getting codex: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": []
            }
    
    def upsert_codex(self, user_no: int, item_type: str, item_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """도감 추가/업데이트"""
        try:
            # SQL 쿼리 예시
            # from models import Codex
            # 
            # existing = self.db.query(Codex).filter(
            #     Codex.user_no == user_no,
            #     Codex.item_type == item_type,
            #     Codex.item_id == item_id
            # ).first()
            # 
            # if existing:
            #     existing.extra_data = data
            #     existing.updated_at = datetime.utcnow()
            # else:
            #     new_item = Codex(
            #         user_no=user_no,
            #         item_type=item_type,
            #         item_id=item_id,
            #         extra_data=data,
            #         completed_at=datetime.utcnow()
            #     )
            #     self.db.add(new_item)
            # 
            # self.db.commit()
            
            self.logger.info(f"Codex upserted: user_no={user_no}, type={item_type}, id={item_id}")
            
            return {
                "success": True,
                "message": "Codex updated",
                "data": {}
            }
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Error upserting codex: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    def sync_batch(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """배치 동기화"""
        try:
            success_count = 0
            
            for item in items:
                result = self.upsert_codex(
                    item['user_no'],
                    item['item_type'],
                    item['item_id'],
                    item['data'].get('data', {})
                )
                if result['success']:
                    success_count += 1
            
            return {
                "success": True,
                "message": f"Synced {success_count}/{len(items)} items",
                "data": {"success_count": success_count}
            }
            
        except Exception as e:
            self.logger.error(f"Error in batch sync: {e}")
            return {
                "success": False,
                "message": f"Batch sync error: {str(e)}",
                "data": {"success_count": 0}
            }
