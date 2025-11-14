# HeroManager.py

from typing import Dict, Any
from sqlalchemy.orm import Session
import models, schemas
from services.system.GameDataManager import GameDataManager
from services.game import ResourceManager, BuffManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime, timedelta
import logging

class HeroManager:
    """영웅 관리자 - 사용자별 영웅 데이터를 관리"""
    
    CONFIG_TYPE = 'hero'
    
    # 영웅 상태 상수 (필요에 따라 정의)
    STATUS_READY = 0
    STATUS_UPGRADING = 1
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_heroes = None  # {hero_idx: hero_data}
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        """사용자 번호의 getter"""
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        """사용자 번호의 setter"""
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_heroes = None

    @property
    def data(self):
        """요청 데이터의 getter"""
        return self._data

    @data.setter
    def data(self, value: dict):
        """요청 데이터의 setter"""
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
    
    def _validate_input(self):
        """공통 입력값 검증 (hero_idx)"""
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }
        
        hero_idx = self.data.get('hero_idx')
        if not hero_idx:
            return {
                "success": False,
                "message": f"Missing required fields: hero_idx: {hero_idx}",
                "data": {}
            }
        
        return None
    
    def _format_hero_for_cache(self, hero_data):
        """캐시용 영웅 데이터 포맷팅"""
        try:
            # 예시 필드: id, user_no, hero_idx, hero_lv, exp, status, last_dt
            data = hero_data if isinstance(hero_data, dict) else hero_data.__dict__
            
            return {
                "id": data.get('id'),
                "user_no": data.get('user_no'),
                "hero_idx": data.get('hero_idx'),
                "hero_lv": data.get('hero_lv'),
                "exp": data.get('exp'),
                "status": data.get('status'),
                "cached_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Error formatting hero data for cache: {e}")
            return {}
            
    async def get_user_heroes(self, user_no: int = None):
        """사용자 영웅 데이터를 캐시 우선으로 조회 (Redis -> DB)"""
        user_no = user_no if user_no is not None else self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            hero_redis = self.redis_manager.get_hero_manager()
            cached_data = await hero_redis.get_cached_heroes(user_no)
            if cached_data:
                self._cached_heroes = cached_data
                return cached_data
            
            # 2. 캐시 미스: DB에서 조회
            heroes_data = self.get_db_heroes(user_no)
            
            # 3. Redis에 캐싱
            if heroes_data['success'] and heroes_data['data']:
                await hero_redis.cache_user_heroes_data(user_no, heroes_data['data'])
                self._cached_heroes = heroes_data['data']
            else:
                self._cached_heroes = {}
                
        except Exception as e:
            self.logger.error(f"Error getting user heroes: {e}")
            self._cached_heroes = {}
        
        return self._cached_heroes
        
    def get_db_heroes(self, user_no):
        """DB에서 영웅 데이터만 순수하게 조회"""
        try:
            hero_db = self.db_manager.get_hero_manager()
            heroes_result = hero_db.get_user_heroes(user_no)
            
            if not heroes_result['success']:
                return heroes_result
            
            formatted_heroes = {}
            for hero in heroes_result['data']:
                hero_idx = hero['hero_idx']
                formatted_heroes[str(hero_idx)] = self._format_hero_for_cache(hero)
            
            return {
                "success": True,
                "message": f"Loaded {len(formatted_heroes)} heroes from database",
                "data": formatted_heroes
            }
            
        except Exception as e:
            self.logger.error(f"Error loading heroes from DB for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
            
    # 이하 _update_cached_hero, hero_info, hero_level_up, hero_equip_item 등 비즈니스 로직 메서드 추가