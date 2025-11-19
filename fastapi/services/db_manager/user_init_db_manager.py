from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
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
    
    def generate_account_no(self) -> Dict[str, Any]:
        """account_no 자동 생성 (마지막 값 + 1)"""
        try:
            # stat_nation에서 가장 큰 account_no 조회
            last_user = self.db.query(models.StatNation).order_by(
                models.StatNation.account_no.desc()
            ).first()
            
            if last_user:
                new_account_no = last_user.account_no + 1
            else:
                # 첫 유저인 경우
                new_account_no = 1
            
            return self._format_response(
                True,
                f"Generated account_no: {new_account_no}",
                {"account_no": new_account_no}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error generating account_no: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error generating account_no: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def create_stat_nation(self, account_no: int) -> Dict[str, Any]:
        """stat_nation 테이블에 기본 데이터 생성 - commit하지 않음"""
        try:
            current_time = datetime.utcnow()
            
            # 새로운 user_no 생성 (auto increment)
            new_stat = models.StatNation(
                account_no=account_no,
                user_no=0,  # auto increment로 자동 생성됨
                cr_dt=current_time,
                last_dt=current_time
            )
            
            self.db.add(new_stat)
            self.db.flush()  # commit 대신 flush
            
            user_no = new_stat.user_no
            
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