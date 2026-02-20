from services.redis_manager import RedisManager
from services.db_manager import DBManager
from typing import Dict, Any, Optional
import logging


class NationManager:
    """
    유저 기본 프로필 관리자
    
    - Redis 캐시 우선 조회, 없으면 DB에서 로드
    - 프로필 데이터: nickname, level, power, alliance_id, alliance_position
    """
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value

    # ==================== API 메서드 ====================

    async def nation_info(self) -> Dict:
        """
        API: 유저 프로필 조회
        
        Request data (optional):
            {"user_no": 1001}  # 없으면 자기 자신
        """
        user_no = self.user_no
        
        try:
            target_no = user_no
            if self._data and self._data.get('user_no'):
                target_no = self._data.get('user_no')
            
            data = await self.get_nation(target_no)
            if not data:
                return {"success": False, "message": "유저 정보를 찾을 수 없습니다"}
            
            return {
                "success": True,
                "data": data
            }
        except Exception as e:
            self.logger.error(f"Error in nation_info: {e}")
            return {"success": False, "message": str(e)}

    # ==================== 내부 메서드 ====================
    
    async def get_nation(self, user_no: int) -> Optional[Dict[str, Any]]:
        """
        유저 프로필 조회 (Redis 우선, 없으면 DB → Redis 캐싱)
        """
        nation_redis = self.redis_manager.get_nation_manager()
        
        # Redis 조회
        data = await nation_redis.get_nation(user_no)
        if data:
            return data
        
        # DB에서 로드 → Redis 캐싱
        data = await self._load_from_db(user_no)
        if data:
            await nation_redis.set_nation(user_no, data)
        
        return data
    
    async def _load_from_db(self, user_no: int) -> Optional[Dict[str, Any]]:
        """DB에서 유저 프로필 로드"""
        try:
            # TODO: 실제 DB 쿼리로 교체
            # stat_nation, alliance_member 테이블 조인 조회
            return self._create_dummy_nation(user_no)
        except Exception as e:
            self.logger.error(f"Error loading nation from DB: {e}")
            return None
    
    def _create_dummy_nation(self, user_no: int) -> Dict[str, Any]:
        """더미 프로필 데이터 생성"""
        return {
            "user_no": user_no,
            "nickname": f"Player_{user_no}",
            "level": 1,
            "power": 0,
            "alliance_id": None,
            "alliance_position": None
        }

    async def update_nation(self, user_no: int, fields: Dict[str, Any]) -> bool:
        """프로필 필드 업데이트 (Redis + DB)"""
        try:
            nation_redis = self.redis_manager.get_nation_manager()
            result = await nation_redis.update_fields(user_no, fields)
            
            # TODO: DB 업데이트 (별도 태스크 또는 즉시)
            
            return result
        except Exception as e:
            self.logger.error(f"Error updating nation: {e}")
            return False