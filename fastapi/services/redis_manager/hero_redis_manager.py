from datetime import datetime
from typing import Optional, List, Dict, Any
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType
import json


class HeroRedisManager:
    """영웅 전용 Redis 관리자 - Cache Manager 컴포넌트 사용 (비동기 버전)"""
    
    def __init__(self, redis_client):
        # Cache Manager 컴포넌트 초기화
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.HERO)
        self.redis_client = redis_client  # 직접 접근용
        
        self.cache_expire_time = 3600  # 1시간
    
    def validate_hero_data(self, hero_id: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """영웅 데이터 유효성 검증"""
        if not hero_id:
            return False
        if metadata:
            required_fields = ['hero_type', 'strength', 'agility', 'vitality']
            for field in required_fields:
                if field not in metadata:
                    return False
        return True
    
    # === Hash 기반 캐싱 관리 메서드들 ===
    
    async def cache_user_heroes_data(self, user_no: int, heroes_data: Dict[str, Any]) -> bool:
        """Hash 구조로 영웅 데이터 캐싱"""
        if not heroes_data:
            return True
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'quantity': len(heroes_data),
                'user_no': user_no
            }
            
            # Cache Manager를 통해 Hash 형태로 저장
            success = await self.cache_manager.set_hash_data(
                hash_key,
                heroes_data,
                expire_time=self.cache_expire_time
            )
            
            if success:
                # 메타데이터도 저장
                await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
                print(f"Successfully cached {len(heroes_data)} heroes for user {user_no} using Hash")
                return True
            
            return False
        
        except Exception as e:
            print(f"Error caching heroes data: {e}")
            return False
    
    async def get_cached_hero(self, user_no: int, hero_id: str) -> Optional[Dict[str, Any]]:
        """특정 영웅 하나만 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            hero_data = await self.cache_manager.get_hash_field(hash_key, str(hero_id))
            
            if hero_data:
                print(f"Cache hit: Retrieved hero {hero_id} for user {user_no}")
                return hero_data
            
            print(f"Cache miss: Hero {hero_id} not found for user {user_no}")
            return None
        
        except Exception as e:
            print(f"Error retrieving cached hero {hero_id} for user {user_no}: {e}")
            return None
    
    async def get_cached_heroes(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 영웅을 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            heroes = await self.cache_manager.get_hash_data(hash_key)
            
            if heroes:
                print(f"Cache hit: Retrieved {len(heroes)} heroes for user {user_no}")
                return heroes
            
            print(f"Cache miss: No cached heroes for user {user_no}")
            return None
        
        except Exception as e:
            print(f"Error retrieving cached heroes for user {user_no}: {e}")
            return None
    
    async def update_cached_hero(self, user_no: int, hero_id: str, hero_data: Dict[str, Any]) -> bool:
        """특정 영웅 캐시 업데이트"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # Cache Manager를 통해 Hash 필드 업데이트
            success = await self.cache_manager.set_hash_field(
                hash_key,
                str(hero_id),
                hero_data,
                expire_time=self.cache_expire_time
            )
            
            if success:
                print(f"Updated cached hero {hero_id} for user {user_no}")
            
            return success
        
        except Exception as e:
            print(f"Error updating cached hero {hero_id} for user {user_no}: {e}")
            return False
    
    async def remove_cached_hero(self, user_no: int, hero_id: str) -> bool:
        """특정 영웅을 캐시에서 제거"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            success = await self.cache_manager.delete_hash_field(hash_key, str(hero_id))
            
            if success:
                print(f"Removed cached hero {hero_id} for user {user_no}")
            
            return success
        
        except Exception as e:
            print(f"Error removing cached hero {hero_id} for user {user_no}: {e}")
            return False
    
    async def invalidate_hero_cache(self, user_no: int) -> bool:
        """사용자 영웅 캐시 전체 무효화"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 두 키 모두 삭제
            hash_deleted = await self.cache_manager.delete_data(hash_key)
            meta_deleted = await self.cache_manager.delete_data(meta_key)
            
            success = hash_deleted or meta_deleted
            if success:
                print(f"Cache invalidated for user {user_no}")
            
            return success
        
        except Exception as e:
            print(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    async def get_cache_info(self, user_no: int) -> Optional[Dict[str, Any]]:
        """캐시 정보 조회"""
        try:
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            meta_data = await self.cache_manager.get_data(meta_key)
            
            if meta_data:
                return meta_data
            
            return None
        
        except Exception as e:
            print(f"Error getting cache info for user {user_no}: {e}")
            return None
    
    # === DB 동기화 큐 관리 메서드들 ===
    
    async def add_to_sync_queue(self, user_no: int, hero_id: str, sync_data: Dict[str, Any]):
        """
        DB 동기화 큐에 추가
        
        완료된 작업을 DB 동기화 큐에 추가합니다.
        CacheSyncManager가 이 큐를 읽어서 DB에 반영합니다.
        """
        try:
            sync_key = f"hero:sync_queue:{user_no}:{hero_id}"
            
            # 기존 동기화 데이터가 있으면 덮어쓰기 (최신 상태만 유지)
            # 저장 (TTL 10분 - 다음 동기화까지 충분)
            await self.redis_client.setex(
                sync_key,
                600,  # 10분
                json.dumps(sync_data)
            )
            
            # 동기화 대기 목록에 추가 (Set)
            await self.redis_client.sadd(
                "hero:sync_pending",
                f"{user_no}:{hero_id}"
            )
            
            print(f"Added to sync queue: user_no={user_no}, hero_id={hero_id}, action={sync_data.get('action')}")
        
        except Exception as e:
            print(f"Error adding to sync queue: {e}")
    
    async def get_sync_queue(self) -> List[Dict[str, Any]]:
        """
        동기화 대기 중인 항목들 조회 (CacheSyncManager용)
        
        Returns:
            List of dicts with keys: user_no, hero_id, data
        """
        try:
            # 동기화 대기 중인 모든 항목 조회
            pending_items = await self.redis_client.smembers("hero:sync_pending")
            
            sync_queue = []
            for item in pending_items:
                item_str = item.decode() if isinstance(item, bytes) else item
                user_no, hero_id = item_str.split(':')
                user_no = int(user_no)
                
                sync_key = f"hero:sync_queue:{user_no}:{hero_id}"
                sync_data = await self.redis_client.get(sync_key)
                
                if sync_data:
                    data_str = sync_data.decode() if isinstance(sync_data, bytes) else sync_data
                    data = json.loads(data_str)
                    
                    sync_queue.append({
                        'user_no': user_no,
                        'hero_id': hero_id,
                        'data': data
                    })
            
            return sync_queue
        
        except Exception as e:
            print(f"Error getting sync queue: {e}")
            return []
    
    async def remove_from_sync_queue(self, user_no: int, hero_id: str):
        """
        DB 동기화 큐에서 제거 (CacheSyncManager용)
        
        동기화가 완료된 항목을 큐에서 제거합니다.
        """
        try:
            sync_key = f"hero:sync_queue:{user_no}:{hero_id}"
            await self.redis_client.delete(sync_key)
            
            # 대기 목록에서도 제거
            await self.redis_client.srem(
                "hero:sync_pending",
                f"{user_no}:{hero_id}"
            )
            
            print(f"Removed from sync queue: user_no={user_no}, hero_id={hero_id}")
        
        except Exception as e:
            print(f"Error removing from sync queue: {e}")
    
    # === 영웅 스탯 관리 메서드들 ===
    
    async def update_hero_stat(self, user_no: int, hero_id: str, stat_name: str, new_value: int) -> bool:
        """
        영웅 특정 스탯 업데이트
        
        Redis 캐시에서 특정 스탯의 값을 변경합니다.
        예: strength, agility, vitality 등
        """
        try:
            current_hero = await self.get_cached_hero(user_no, hero_id)
            
            if current_hero:
                current_hero[stat_name] = new_value
                current_hero['cached_at'] = datetime.utcnow().isoformat()
                await self.update_cached_hero(user_no, hero_id, current_hero)
                
                print(f"Updated {stat_name} to {new_value} for hero {hero_id}")
                return True
            else:
                print(f"Hero {hero_id} not found in cache, cannot update stat")
                return False
        
        except Exception as e:
            print(f"Error updating hero stat: {e}")
            return False
    
    async def increment_hero_level(self, user_no: int, hero_id: str, level_increase: int = 1) -> bool:
        """
        영웅 레벨 증가
        
        Redis 캐시에서 영웅의 레벨을 증가시킵니다.
        """
        try:
            current_hero = await self.get_cached_hero(user_no, hero_id)
            
            if current_hero:
                current_level = current_hero.get('level', 1)
                new_level = current_level + level_increase
                current_hero['level'] = new_level
                current_hero['cached_at'] = datetime.utcnow().isoformat()
                await self.update_cached_hero(user_no, hero_id, current_hero)
                
                print(f"Increased level to {new_level} for hero {hero_id}")
                return True
            else:
                print(f"Hero {hero_id} not found in cache, cannot increment level")
                return False
        
        except Exception as e:
            print(f"Error incrementing hero level: {e}")
            return False
    
    async def add_hero_experience(self, user_no: int, hero_id: str, exp_amount: int) -> bool:
        """
        영웅 경험치 추가
        
        Redis 캐시에서 영웅의 경험치를 추가합니다.
        """
        try:
            current_hero = await self.get_cached_hero(user_no, hero_id)
            
            if current_hero:
                current_exp = current_hero.get('experience', 0)
                new_exp = current_exp + exp_amount
                current_hero['experience'] = new_exp
                current_hero['cached_at'] = datetime.utcnow().isoformat()
                await self.update_cached_hero(user_no, hero_id, current_hero)
                
                print(f"Added {exp_amount} experience to hero {hero_id} (new total: {new_exp})")
                return True
            else:
                print(f"Hero {hero_id} not found in cache, cannot add experience")
                return False
        
        except Exception as e:
            print(f"Error adding hero experience: {e}")
            return False