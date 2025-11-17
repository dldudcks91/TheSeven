# HeroManager.py

from typing import Dict, Any
from datetime import datetime
import random
import logging


class HeroManager:
    """영웅 관리 매니저 - Redis 캐싱 우선, DB 동기화"""
    
    CONFIG_TYPE = 'hero'
    
    # 영웅 타입별 스탯 범위 설정
    HERO_STAT_RANGES = {
        "warrior": {
            "name": "전사",
            "strength": (8, 12),
            "agility": (4, 8),
            "vitality": (10, 15)
        },
        "archer": {
            "name": "궁수",
            "strength": (5, 9),
            "agility": (10, 15),
            "vitality": (6, 10)
        },
        "mage": {
            "name": "마법사",
            "strength": (3, 6),
            "agility": (6, 10),
            "vitality": (5, 8)
        },
        "assassin": {
            "name": "암살자",
            "strength": (6, 9),
            "agility": (12, 16),
            "vitality": (4, 7)
        },
        "paladin": {
            "name": "성기사",
            "strength": (10, 14),
            "agility": (3, 6),
            "vitality": (12, 17)
        }
    }
    
    def __init__(self, db_manager, redis_manager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_heroes = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        """사용자 번호의 getter"""
        return self._user_no
    
    @user_no.setter
    def user_no(self, no: int):
        """사용자 번호의 setter. 정수형인지 확인"""
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
        """요청 데이터의 setter. 딕셔너리인지 확인"""
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
    
    def _validate_input(self):
        """공통 입력값 검증"""
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }
        
        hero_id = self.data.get('hero_id')
        if not hero_id:
            return {
                "success": False,
                "message": f"Missing required fields: hero_id: {hero_id}",
                "data": {}
            }
        
        return None
    
    def _generate_random_stats(self, hero_type: str) -> Dict[str, int]:
        """영웅 타입에 맞는 랜덤 스탯 생성"""
        if hero_type not in self.HERO_STAT_RANGES:
            raise ValueError(f"Unknown hero type: {hero_type}")
        
        config = self.HERO_STAT_RANGES[hero_type]
        return {
            "strength": random.randint(*config["strength"]),
            "agility": random.randint(*config["agility"]),
            "vitality": random.randint(*config["vitality"])
        }
    
    def _format_hero_for_cache(self, hero_data):
        """캐시용 영웅 데이터 포맷팅"""
        try:
            if isinstance(hero_data, dict):
                return {
                    "id": hero_data.get('id'),
                    "user_no": hero_data.get('user_no'),
                    "hero_type": hero_data.get('hero_type'),
                    "name": hero_data.get('name'),
                    "strength": hero_data.get('strength'),
                    "agility": hero_data.get('agility'),
                    "vitality": hero_data.get('vitality'),
                    "level": hero_data.get('level', 1),
                    "experience": hero_data.get('experience', 0),
                    "cached_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "id": hero_data.id,
                    "user_no": hero_data.user_no,
                    "hero_type": hero_data.hero_type,
                    "name": hero_data.name,
                    "strength": hero_data.strength,
                    "agility": hero_data.agility,
                    "vitality": hero_data.vitality,
                    "level": hero_data.level,
                    "experience": hero_data.experience,
                    "cached_at": datetime.utcnow().isoformat()
                }
        except Exception as e:
            self.logger.error(f"Error formatting hero data for cache: {e}")
            return {}
    
    async def get_user_heroes(self, user_no: int = None):
        """사용자 영웅 데이터를 캐시 우선으로 조회"""
        user_no = user_no if user_no is not None else self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            hero_redis = self.redis_manager.get_hero_manager()
            self._cached_heroes = await hero_redis.get_cached_heroes(user_no)
            self.logger.debug(self._cached_heroes)
            
            if self._cached_heroes:
                self.logger.debug(f"Cache hit: Retrieved {len(self._cached_heroes)} heroes for user {user_no}")
                return self._cached_heroes
            
            # 2. 캐시 미스: DB에서 조회
            heroes_data = self.get_db_heroes(user_no)
            
            if heroes_data['success'] and heroes_data['data']:
                # 3. Redis에 캐싱
                cache_success = await hero_redis.cache_user_heroes_data(user_no, heroes_data['data'])
                if cache_success:
                    self.logger.debug(f"Successfully cached {len(heroes_data['data'])} heroes for user {user_no}")
                
                self._cached_heroes = heroes_data['data']
            else:
                self._cached_heroes = {}
        
        except Exception as e:
            self.logger.error(f"Error getting user heroes for user {user_no}: {e}")
            self._cached_heroes = {}
        
        return self._cached_heroes
    
    def get_db_heroes(self, user_no):
        """DB에서 영웅 데이터만 순수하게 조회"""
        try:
            hero_db = self.db_manager.get_hero_manager()
            heroes_result = hero_db.get_user_heroes(user_no)
            
            if not heroes_result['success']:
                return heroes_result
            
            # 데이터 포맷팅
            formatted_heroes = {}
            for hero in heroes_result['data']:
                hero_id = hero['id']
                formatted_heroes[str(hero_id)] = self._format_hero_for_cache(hero)
            
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
    
    async def create_hero(self):
        """새로운 영웅 생성"""
        try:
            user_no = self.user_no
            
            if not self._data:
                return {
                    "success": False,
                    "message": "Missing required data payload",
                    "data": {}
                }
            
            hero_type = self.data.get('hero_type')
            custom_name = self.data.get('name')
            
            if not hero_type or hero_type not in self.HERO_STAT_RANGES:
                return {
                    "success": False,
                    "message": f"Invalid hero_type: {hero_type}",
                    "data": {}
                }
            
            # 랜덤 스탯 생성
            stats = self._generate_random_stats(hero_type)
            
            # 기본 이름 설정
            name = custom_name if custom_name else self.HERO_STAT_RANGES[hero_type]["name"]
            
            # 영웅 데이터 준비
            hero_data = {
                "user_no": user_no,
                "hero_type": hero_type,
                "name": name,
                "strength": stats["strength"],
                "agility": stats["agility"],
                "vitality": stats["vitality"],
                "level": 1,
                "experience": 0
            }
            
            # Redis에 먼저 저장
            hero_redis = self.redis_manager.get_hero_manager()
            
            # 임시 ID 생성 (나중에 DB에서 실제 ID로 업데이트)
            temp_id = f"temp_{user_no}_{datetime.utcnow().timestamp()}"
            hero_data["id"] = temp_id
            
            # Redis 캐시에 추가
            formatted_hero = self._format_hero_for_cache(hero_data)
            await hero_redis.update_cached_hero(user_no, temp_id, formatted_hero)
            
            # DB 동기화 큐에 추가
            sync_data = {
                "action": "create",
                "hero_data": hero_data,
                "timestamp": datetime.utcnow().isoformat()
            }
            await hero_redis.add_to_sync_queue(user_no, temp_id, sync_data)
            
            self.logger.info(f"Hero created: user_no={user_no}, hero_type={hero_type}")
            
            return {
                "success": True,
                "message": "Hero created successfully",
                "data": formatted_hero
            }
        
        except Exception as e:
            self.logger.error(f"Error creating hero: {e}")
            return {
                "success": False,
                "message": f"Error creating hero: {str(e)}",
                "data": {}
            }
    
    async def reroll_hero_stats(self):
        """영웅 스탯 재배치 (새로고침)"""
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            hero_id = str(self.data.get('hero_id'))
            
            # 캐시에서 영웅 조회
            heroes_data = await self.get_user_heroes(user_no)
            hero = heroes_data.get(hero_id)
            
            if not hero:
                return {
                    "success": False,
                    "message": f"Hero not found: {hero_id}",
                    "data": {}
                }
            
            # 새로운 랜덤 스탯 생성
            hero_type = hero['hero_type']
            new_stats = self._generate_random_stats(hero_type)
            
            # 영웅 데이터 업데이트
            hero['strength'] = new_stats['strength']
            hero['agility'] = new_stats['agility']
            hero['vitality'] = new_stats['vitality']
            hero['cached_at'] = datetime.utcnow().isoformat()
            
            # Redis 캐시 업데이트
            hero_redis = self.redis_manager.get_hero_manager()
            await hero_redis.update_cached_hero(user_no, hero_id, hero)
            
            # DB 동기화 큐에 추가
            sync_data = {
                "action": "reroll",
                "hero_id": hero_id,
                "new_stats": new_stats,
                "timestamp": datetime.utcnow().isoformat()
            }
            await hero_redis.add_to_sync_queue(user_no, hero_id, sync_data)
            
            self.logger.info(f"Hero stats rerolled: user_no={user_no}, hero_id={hero_id}")
            
            return {
                "success": True,
                "message": "Hero stats rerolled successfully",
                "data": hero
            }
        
        except Exception as e:
            self.logger.error(f"Error rerolling hero stats: {e}")
            return {
                "success": False,
                "message": f"Error rerolling hero stats: {str(e)}",
                "data": {}
            }
    
    async def get_hero_by_id(self):
        """특정 영웅 조회"""
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            hero_id = str(self.data.get('hero_id'))
            
            # 캐시에서 조회
            heroes_data = await self.get_user_heroes(user_no)
            hero = heroes_data.get(hero_id)
            
            if not hero:
                return {
                    "success": False,
                    "message": f"Hero not found: {hero_id}",
                    "data": {}
                }
            
            return {
                "success": True,
                "message": "Hero retrieved successfully",
                "data": hero
            }
        
        except Exception as e:
            self.logger.error(f"Error getting hero: {e}")
            return {
                "success": False,
                "message": f"Error getting hero: {str(e)}",
                "data": {}
            }
    
    async def delete_hero(self):
        """영웅 삭제"""
        try:
            user_no = self.user_no
            
            # 입력값 검증
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            hero_id = str(self.data.get('hero_id'))
            
            # 캐시에서 영웅 확인
            heroes_data = await self.get_user_heroes(user_no)
            hero = heroes_data.get(hero_id)
            
            if not hero:
                return {
                    "success": False,
                    "message": f"Hero not found: {hero_id}",
                    "data": {}
                }
            
            # Redis 캐시에서 제거
            hero_redis = self.redis_manager.get_hero_manager()
            await hero_redis.remove_cached_hero(user_no, hero_id)
            
            # DB 동기화 큐에 추가
            sync_data = {
                "action": "delete",
                "hero_id": hero_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            await hero_redis.add_to_sync_queue(user_no, hero_id, sync_data)
            
            self.logger.info(f"Hero deleted: user_no={user_no}, hero_id={hero_id}")
            
            return {
                "success": True,
                "message": "Hero deleted successfully",
                "data": {}
            }
        
        except Exception as e:
            self.logger.error(f"Error deleting hero: {e}")
            return {
                "success": False,
                "message": f"Error deleting hero: {str(e)}",
                "data": {}
            }
    
    async def invalidate_user_hero_cache(self, user_no: int):
        """사용자 영웅 캐시 무효화"""
        try:
            hero_redis = self.redis_manager.get_hero_manager()
            cache_invalidated = await hero_redis.invalidate_hero_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_heroes = None
            
            self.logger.debug(f"Cache invalidated for user {user_no}: {cache_invalidated}")
            return cache_invalidated
        
        except Exception as e:
            self.logger.error(f"Error invalidating cache for user {user_no}: {e}")
            return False