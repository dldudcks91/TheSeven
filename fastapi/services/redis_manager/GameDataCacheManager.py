# services/game_data_cache_manager.py
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from services.redis_manager import RedisManager

class GameDataCacheManager:
    """게임 데이터 통합 Redis 캐싱 관리자"""
    
    def __init__(self, redis_manager: RedisManager):
        self.redis_manager = redis_manager
        self.cache_prefixes = {
            'buildings': 'user_buildings',
            'units': 'user_units',
            'research': 'user_research',
            'resources': 'user_resources',
            'buffs': 'user_buffs'
        }
        self.cache_expire_time = 3600  # 1시간
    
    def _get_cache_key(self, data_type: str, user_no: int) -> str:
        """데이터 타입별 캐시 키 생성"""
        prefix = self.cache_prefixes.get(data_type)
        if not prefix:
            raise ValueError(f"Unknown data type: {data_type}")
        return f"{prefix}:{user_no}"
    
    def cache_user_data(self, user_no: int, data_type: str, data: Dict[str, Any]) -> bool:
        """사용자 데이터를 Redis에 캐싱"""
        try:
            cache_key = self._get_cache_key(data_type, user_no)
            
            cache_data = {
                'data': data,
                'cached_at': datetime.utcnow().isoformat(),
                'user_no': user_no,
                'data_type': data_type
            }
            
            self.redis_manager.redis_client.setex(
                cache_key, 
                self.cache_expire_time, 
                json.dumps(cache_data, default=str)
            )
            
            print(f"Cached {data_type} for user {user_no}: {len(data)} items")
            return True
            
        except Exception as e:
            print(f"Error caching {data_type} for user {user_no}: {e}")
            return False
    
    def get_cached_data(self, user_no: int, data_type: str) -> Optional[Dict[str, Any]]:
        """Redis에서 사용자 데이터 조회"""
        try:
            cache_key = self._get_cache_key(data_type, user_no)
            cached_data = self.redis_manager.redis_client.get(cache_key)
            
            if cached_data:
                data = json.loads(cached_data)
                return data.get('data', {})
            
            return None
            
        except Exception as e:
            print(f"Error retrieving cached {data_type} for user {user_no}: {e}")
            return None
    
    def invalidate_user_cache(self, user_no: int, data_type: str = None) -> bool:
        """사용자 캐시 무효화 (전체 또는 특정 타입)"""
        try:
            if data_type:
                # 특정 데이터 타입만 삭제
                cache_key = self._get_cache_key(data_type, user_no)
                result = self.redis_manager.redis_client.delete(cache_key)
                print(f"Invalidated {data_type} cache for user {user_no}")
                return result > 0
            else:
                # 모든 데이터 타입 삭제
                deleted_count = 0
                for data_type in self.cache_prefixes.keys():
                    cache_key = self._get_cache_key(data_type, user_no)
                    deleted_count += self.redis_manager.redis_client.delete(cache_key)
                print(f"Invalidated all cache for user {user_no}")
                return deleted_count > 0
                
        except Exception as e:
            print(f"Error invalidating cache for user {user_no}: {e}")
            return False
    
    def update_item_in_cache(self, user_no: int, data_type: str, item_key: str, item_data: Dict[str, Any]) -> bool:
        """캐시에서 특정 아이템 업데이트"""
        try:
            cached_data = self.get_cached_data(user_no, data_type)
            if cached_data is None:
                return False
            
            cached_data[str(item_key)] = item_data
            return self.cache_user_data(user_no, data_type, cached_data)
            
        except Exception as e:
            print(f"Error updating {data_type} item {item_key} in cache for user {user_no}: {e}")
            return False



