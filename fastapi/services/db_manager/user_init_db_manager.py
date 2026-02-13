from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import func
import models
from datetime import datetime
import logging


class UserInitDBManager:
    """유저 초기화 전용 DB 관리자 - account_no와 user_no 모두 Counter로 관리"""
    
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
    
    def _ensure_counter_exists(self, counter_type: str) -> None:
        """
        Counter가 존재하는지 확인하고 없으면 생성
        서버 첫 시작시 자동으로 초기화
        
        Args:
            counter_type: 'account_no' 또는 'user_no'
        """
        try:
            counter = self.db.query(models.IDCounter).filter(
                models.IDCounter.counter_type == counter_type
            ).first()
            
            if not counter:
                # Counter가 없으면 현재 DB의 최대값으로 초기화
                if counter_type == 'account_no':
                    max_value = self.db.query(
                        func.max(models.StatNation.account_no)
                    ).scalar() or 0
                elif counter_type == 'user_no':
                    max_value = self.db.query(
                        func.max(models.StatNation.user_no)
                    ).scalar() or 0
                else:
                    max_value = 0
                
                new_counter = models.IDCounter(
                    counter_type=counter_type,
                    current_value=max_value
                )
                self.db.add(new_counter)
                self.db.flush()
                
                self.logger.info(
                    f"Initialized counter '{counter_type}' with value {max_value}"
                )
                
        except Exception as e:
            self.logger.error(f"Error ensuring counter exists: {e}")
            raise
    
    def _generate_next_id(self, counter_type: str) -> int:
        """
        Counter에서 다음 ID 생성 (내부 헬퍼)
        
        Args:
            counter_type: 'account_no' 또는 'user_no'
            
        Returns:
            int: 생성된 ID
        """
        try:
            # 1. Counter 존재 확인
            self._ensure_counter_exists(counter_type)
            
            # 2. Counter row를 FOR UPDATE로 lock하고 조회
            counter = self.db.query(models.IDCounter).filter(
                models.IDCounter.counter_type == counter_type
            ).with_for_update().first()
            
            # 3. 값 증가 (원자적 연산)
            counter.current_value += 1
            new_id = counter.current_value
            
            # 4. flush (commit은 상위에서)
            self.db.flush()
            
            self.logger.debug(f"Generated {counter_type}: {new_id} (atomic)")
            
            return new_id
            
        except Exception as e:
            self.logger.error(f"Error generating {counter_type}: {e}")
            raise
    
    def generate_next_ids(self) -> Dict[str, Any]:
        """
        account_no와 user_no를 동시에 생성
        한 트랜잭션에서 두 Counter 모두 증가
        
        Returns:
            {
                "success": bool, 
                "message": str, 
                "data": {"account_no": int, "user_no": int}
            }
        """
        try:
            # 1. account_no 생성
            account_no = self._generate_next_id('account_no')
            
            # 2. user_no 생성
            user_no = self._generate_next_id('user_no')
            
            self.logger.debug(
                f"Generated IDs - account_no: {account_no}, user_no: {user_no}"
            )
            
            return self._format_response(
                True,
                f"Generated account_no: {account_no}, user_no: {user_no}",
                {
                    "account_no": account_no,
                    "user_no": user_no
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error generating IDs: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error generating IDs: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def generate_next_account_no(self) -> Dict[str, Any]:
        """
        다음 account_no만 생성 (하위 호환성)
        
        Returns:
            {"success": bool, "message": str, "data": {"account_no": int}}
        """
        try:
            account_no = self._generate_next_id('account_no')
            
            return self._format_response(
                True,
                f"Generated account_no: {account_no}",
                {"account_no": account_no}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error generating account_no: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error generating account_no: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def generate_next_user_no(self) -> Dict[str, Any]:
        """
        다음 user_no만 생성 (하위 호환성)
        
        Returns:
            {"success": bool, "message": str, "data": {"user_no": int}}
        """
        try:
            user_no = self._generate_next_id('user_no')
            
            return self._format_response(
                True,
                f"Generated user_no: {user_no}",
                {"user_no": user_no}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error generating user_no: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error generating user_no: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def create_stat_nation(self, account_no: int, user_no: int) -> Dict[str, Any]:
        """
        stat_nation 테이블에 데이터 생성
        account_no와 user_no 모두 Counter에서 생성된 값 사용
        
        Args:
            account_no: Counter에서 생성된 계정 번호
            user_no: Counter에서 생성된 유저 번호
            
        Returns:
            {"success": bool, "message": str, "data": {"user_no": int, "account_no": int}}
        """
        try:
            current_time = datetime.utcnow()
            
            # Counter에서 생성된 ID로 새 레코드 생성
            new_stat = models.StatNation(
                account_no=account_no,
                user_no=user_no,
                cr_dt=current_time,
                last_dt=current_time
            )
            
            self.db.add(new_stat)
            self.db.flush()
            
            self.logger.debug(
                f"Created stat_nation: account_no={account_no}, user_no={user_no}"
            )
            
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
            
        except IntegrityError as e:
            # account_no 또는 user_no 중복 에러 (거의 불가능하지만 방어 코드)
            self.logger.error(f"Integrity error creating stat_nation: {e}")
            return self._format_response(
                False, 
                f"Duplicate ID - account_no: {account_no}, user_no: {user_no}. This should not happen!"
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
            self.db.flush()
            
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
            self.db.flush()
            
            return self._format_response(
                True,
                "Building created successfully",
                {
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
        통계용
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
    
    def get_total_user_count(self) -> Dict[str, Any]:
        """전체 유저 수 조회"""
        try:
            total_count = self.db.query(func.count(models.StatNation.user_no)).scalar()
            
            return self._format_response(
                True,
                f"Total users: {total_count}",
                {"total_count": total_count}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user count: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting user count: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def get_counter_value(self, counter_type: str) -> Dict[str, Any]:
        """
        Counter의 현재 값 조회 (디버깅/통계용)
        
        Args:
            counter_type: 'account_no' 또는 'user_no'
        """
        try:
            counter = self.db.query(models.IDCounter).filter(
                models.IDCounter.counter_type == counter_type
            ).first()
            
            if not counter:
                return self._format_response(
                    False,
                    f"Counter '{counter_type}' not found",
                    {"current_value": 0}
                )
            
            return self._format_response(
                True,
                f"Counter value retrieved",
                {
                    "counter_type": counter_type,
                    "current_value": counter.current_value
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting counter: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting counter: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def get_all_counter_values(self) -> Dict[str, Any]:
        """
        모든 Counter 값 조회 (디버깅/통계용)
        """
        try:
            counters = self.db.query(models.IDCounter).all()
            
            counter_data = {
                counter.counter_type: counter.current_value
                for counter in counters
            }
            
            return self._format_response(
                True,
                f"Retrieved {len(counter_data)} counters",
                {"counters": counter_data}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting counters: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error getting counters: {e}")
            return self._format_response(False, f"Error: {str(e)}")
    
    def reset_counter(self, counter_type: str, value: int) -> Dict[str, Any]:
        """
        Counter 값 수동 리셋 (관리자 기능)
        ⚠️ 주의: 프로덕션에서는 신중하게 사용!
        
        Args:
            counter_type: 'account_no' 또는 'user_no'
            value: 새로운 값
        """
        try:
            counter = self.db.query(models.IDCounter).filter(
                models.IDCounter.counter_type == counter_type
            ).with_for_update().first()
            
            if not counter:
                return self._format_response(
                    False,
                    f"Counter '{counter_type}' not found"
                )
            
            old_value = counter.current_value
            counter.current_value = value
            self.db.flush()
            
            self.logger.warning(
                f"Counter '{counter_type}' reset: {old_value} → {value}"
            )
            
            return self._format_response(
                True,
                f"Counter reset successfully",
                {
                    "counter_type": counter_type,
                    "old_value": old_value,
                    "new_value": value
                }
            )
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database error resetting counter: {e}")
            return self._format_response(False, f"Database error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error resetting counter: {e}")
            return self._format_response(False, f"Error: {str(e)}")