from datetime import datetime
from typing import Optional, Dict, Any, List
import json


class CodexRedisManager:
    """통합 도감 Redis 관리자"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간
    
    async def update_codex_item(self, user_no: int, item_type: str, item_id: int, data: Dict[str, Any]):
        """도감 항목 업데이트"""
        try:
            key = f"{item_type}_{item_id}"
            
            await self.redis_client.hset(
                f"codex:user:{user_no}",
                key,
                json.dumps(data)
            )
            
            # 만료 시간 설정
            await self.redis_client.expire(f"codex:user:{user_no}", self.cache_expire_time)
            
            print(f"Updated codex: user={user_no}, type={item_type}, id={item_id}")
            
        except Exception as e:
            print(f"Error updating codex item: {e}")
    
    async def get_codex(self, user_no: int) -> Optional[Dict[str, Any]]:
        """전체 도감 조회"""
        try:
            codex_hash = await self.redis_client.hgetall(f"codex:user:{user_no}")
            
            if not codex_hash:
                print(f"No codex found for user {user_no}")
                return None
            
            result = {}
            for key, value in codex_hash.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                value_str = value.decode() if isinstance(value, bytes) else value
                result[key_str] = json.loads(value_str)
            
            print(f"Retrieved {len(result)} codex items for user {user_no}")
            return result
            
        except Exception as e:
            print(f"Error getting codex: {e}")
            return None
    
    async def cache_codex(self, user_no: int, codex: Dict[str, Any]):
        """도감 캐싱"""
        try:
            if not codex:
                return True
            
            for key, value in codex.items():
                await self.redis_client.hset(
                    f"codex:user:{user_no}",
                    key,
                    json.dumps(value)
                )
            
            await self.redis_client.expire(f"codex:user:{user_no}", self.cache_expire_time)
            
            print(f"Cached {len(codex)} codex items for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error caching codex: {e}")
            return False
    
    async def invalidate_cache(self, user_no: int):
        """캐시 무효화"""
        try:
            await self.redis_client.delete(f"codex:user:{user_no}")
            print(f"Codex cache invalidated for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error invalidating cache: {e}")
            return False
    
    # ===== DB 동기화 큐 =====
    
    async def add_to_sync_queue(self, user_no: int, item_type: str, item_id: int, sync_data: Dict[str, Any]):
        """DB 동기화 큐에 추가"""
        try:
            sync_key = f"codex:sync:{user_no}:{item_type}:{item_id}"
            
            await self.redis_client.setex(
                sync_key,
                600,  # 10분
                json.dumps(sync_data)
            )
            
            await self.redis_client.sadd("codex:sync_pending", f"{user_no}:{item_type}:{item_id}")
            
            print(f"Added to sync queue: user={user_no}, type={item_type}, id={item_id}")
            
        except Exception as e:
            print(f"Error adding to sync queue: {e}")
    
    async def get_sync_queue(self) -> List[Dict[str, Any]]:
        """동기화 대기 항목 조회"""
        try:
            pending = await self.redis_client.smembers("codex:sync_pending")
            
            queue = []
            for item in pending:
                item_str = item.decode() if isinstance(item, bytes) else item
                parts = item_str.split(':')
                if len(parts) != 3:
                    continue
                
                user_no, item_type, item_id = parts
                sync_key = f"codex:sync:{user_no}:{item_type}:{item_id}"
                sync_data = await self.redis_client.get(sync_key)
                
                if sync_data:
                    data_str = sync_data.decode() if isinstance(sync_data, bytes) else sync_data
                    queue.append({
                        'user_no': int(user_no),
                        'item_type': item_type,
                        'item_id': int(item_id),
                        'data': json.loads(data_str)
                    })
            
            return queue
            
        except Exception as e:
            print(f"Error getting sync queue: {e}")
            return []
    
    async def remove_from_sync_queue(self, user_no: int, item_type: str, item_id: int):
        """동기화 큐에서 제거"""
        try:
            sync_key = f"codex:sync:{user_no}:{item_type}:{item_id}"
            await self.redis_client.delete(sync_key)
            await self.redis_client.srem("codex:sync_pending", f"{user_no}:{item_type}:{item_id}")
            
            print(f"Removed from sync queue: user={user_no}, type={item_type}, id={item_id}")
            
        except Exception as e:
            print(f"Error removing from sync queue: {e}")
