from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
import models
from datetime import datetime
import logging


class UserInitDBManager:
    """유저 초기화 전용 DB 관리자 - 순수 데이터 조회/저장만 담당"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        """응답 형태 통일"""
        return {
            "success": success,
            "message": message,
            "data": data or {}
        }
    
    def create_stat_nation(self, account_no: int, user_no: int) -> Dict[str, Any]:
        """
        stat_nation 테이블에 데이터 생성
        account_no와 user_no는 이미 Redis에서 생성된 값을 받음
        
        Args:
            account_no: Redis에서 생성된 계정 번호
            user_no: Redis에서 생성된 유저 번호
        """
        try:
            current_time = datetime.utcnow()
            
            # Redis에서 생성된 ID로 새 레코드 생성
            new_stat = models.StatNation(
                account_no=account_no,
                user_no=user_no,
                cr_dt=current_time,
                last_dt=current_time
            )
            
            self.db.add(new_stat)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "stat_nation created successfully",
                {
                    "user_no": user_no,
                    "account_no": account_no,
                    "cr_dt": current_time.isoformat(),
                    "last_dt": current_time.isoformat()
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating stat_nation: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating stat_nation: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def create_resources(self, user_no: int, resources: Dict[str, int]) -> Dict[str, Any]:
        """초기 자원 생성 - commit하지 않음"""
        try:
            new_resources = models.Resources(
                user_no=user_no,
                food=resources.get("food", 0),
                wood=resources.get("wood", 0),
                stone=resources.get("stone", 0),
                gold=resources.get("gold", 0),
                ruby=resources.get("ruby", 0)
            )
            
            self.db.add(new_resources)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Resources created successfully",
                {
                    "user_no": user_no,
                    "food": resources.get("food", 0),
                    "wood": resources.get("wood", 0),
                    "stone": resources.get("stone", 0),
                    "gold": resources.get("gold", 0),
                    "ruby": resources.get("ruby", 0)
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating resources: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating resources: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def create_building(self, user_no: int, building_config: Dict[str, Any]) -> Dict[str, Any]:
        """초기 건물 생성 - commit하지 않음"""
        try:
            current_time = datetime.utcnow()
            
            new_building = models.Building(
                user_no=user_no,
                building_idx=building_config["building_idx"],
                building_lv=building_config["building_lv"],
                status=building_config["status"],
                start_time=None,
                end_time=None,
                last_dt=current_time
            )
            
            self.db.add(new_building)
            self.db.flush()  # commit 대신 flush
            
            return self._format_response(
                True,
                "Building created successfully",
                {
                    "id": new_building.id,
                    "user_no": user_no,
                    "building_idx": building_config["building_idx"],
                    "building_lv": building_config["building_lv"],
                    "status": building_config["status"]
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating building: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating building: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def create_batch_buildings(self, user_no: int, building_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """여러 건물을 한번에 생성 (성능 최적화)"""
        try:
            current_time = datetime.utcnow()
            created_buildings = []
            
            for config in building_configs:
                new_building = models.Building(
                    user_no=user_no,
                    building_idx=config["building_idx"],
                    building_lv=config["building_lv"],
                    status=config["status"],
                    start_time=None,
                    end_time=None,
                    last_dt=current_time
                )
                self.db.add(new_building)
                created_buildings.append({
                    "building_idx": config["building_idx"],
                    "building_lv": config["building_lv"]
                })
            
            self.db.flush()
            
            return self._format_response(
                True,
                f"Created {len(created_buildings)} buildings",
                {"buildings": created_buildings}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error creating batch buildings: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error creating batch buildings: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def check_user_exists(self, account_no: int) -> Dict[str, Any]:
        """계정번호로 유저 존재 여부 확인"""
        try:
            existing_user = self.db.query(models.StatNation).filter(
                models.StatNation.account_no == account_no
            ).first()
            
            exists = existing_user is not None
            
            if exists:
                return self._format_response(
                    True,
                    "User exists",
                    {
                        "exists": True,
                        "user_no": existing_user.user_no,
                        "account_no": existing_user.account_no
                    }
                )
            else:
                return self._format_response(
                    True,
                    "User does not exist",
                    {"exists": False}
                )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error checking user existence: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error checking user existence: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def get_user_by_account_no(self, account_no: int) -> Dict[str, Any]:
        """계정번호로 유저 정보 조회"""
        try:
            user = self.db.query(models.StatNation).filter(
                models.StatNation.account_no == account_no
            ).first()
            
            if not user:
                return self._format_response(False, "User not found")
            
            return self._format_response(
                True,
                "User retrieved successfully",
                {
                    "user_no": user.user_no,
                    "account_no": user.account_no,
                    "cr_dt": user.cr_dt.isoformat() if user.cr_dt else None,
                    "last_dt": user.last_dt.isoformat() if user.last_dt else None
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting user: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def get_max_ids(self) -> Dict[str, Any]:
        """
        DB에서 현재 최대 account_no와 user_no 조회
        Redis 초기화시 사용
        """
        try:
            max_account_no = self.db.query(
                func.max(models.StatNation.account_no)
            ).scalar() or 0
            
            max_user_no = self.db.query(
                func.max(models.StatNation.user_no)
            ).scalar() or 0
            
            return self._format_response(
                True,
                "Max IDs retrieved",
                {
                    "max_account_no": max_account_no,
                    "max_user_no": max_user_no
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting max IDs: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting max IDs: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def get_recent_users(self, limit: int = 10) -> Dict[str, Any]:
        """최근 생성된 유저 목록 조회"""
        try:
            recent_users = self.db.query(models.StatNation).order_by(
                models.StatNation.cr_dt.desc()
            ).limit(limit).all()
            
            users_data = [
                {
                    "user_no": user.user_no,
                    "account_no": user.account_no,
                    "cr_dt": user.cr_dt.isoformat() if user.cr_dt else None
                }
                for user in recent_users
            ]
            
            return self._format_response(
                True,
                f"Retrieved {len(users_data)} recent users",
                {"users": users_data}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting recent users: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting recent users: {e}")
            return self._format_response(False, f"Error: {str(e)}")