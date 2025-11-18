from datetime import datetime
from typing import Dict, Any, List
import json


class MissionRedisManager:
    """미션 Redis 관리자 - 완료 상태 캐싱"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간
    
    async def get_user_missions(self, user_no: int) -> List[Dict[str, Any]]:
        """사용자 미션 조회 (Config + 완료 상태)"""
        try:
            missions_data = await self.redis_client.get(f"mission:user:{user_no}")
            
            if not missions_data:
                return []
            
            data_str = missions_data.decode() if isinstance(missions_data, bytes) else missions_data
            missions = json.loads(data_str)
            
            print(f"Retrieved {len(missions)} missions for user {user_no}")
            return missions
            
        except Exception as e:
            print(f"Error getting user missions: {e}")
            return []
    
    async def cache_user_missions(self, user_no: int, missions: List[Dict[str, Any]]):
        """사용자 미션 캐싱"""
        try:
            await self.redis_client.setex(
                f"mission:user:{user_no}",
                self.cache_expire_time,
                json.dumps(missions)
            )
            
            print(f"Cached {len(missions)} missions for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error caching missions: {e}")
            return False
    
    async def complete_mission(self, user_no: int, mission_idx: int):
        """미션 완료 처리"""
        try:
            # 캐시에서 미션 업데이트
            missions = await self.get_user_missions(user_no)
            
            if missions:
                for mission in missions:
                    if mission['mission_idx'] == mission_idx:
                        mission['completed'] = True
                        mission['completed_at'] = datetime.utcnow().isoformat()
                        break
                
                # 업데이트된 미션 목록 저장
                await self.cache_user_missions(user_no, missions)
            
            # 완료된 미션 Set에 추가
            await self.redis_client.sadd(
                f"mission:completed:{user_no}",
                str(mission_idx)
            )
            
            print(f"Mission {mission_idx} completed for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error completing mission: {e}")
            return False
    
    async def is_mission_completed(self, user_no: int, mission_idx: int) -> bool:
        """미션 완료 여부 확인"""
        try:
            is_completed = await self.redis_client.sismember(
                f"mission:completed:{user_no}",
                str(mission_idx)
            )
            
            return bool(is_completed)
            
        except Exception as e:
            print(f"Error checking mission completion: {e}")
            return False
    
    async def invalidate_cache(self, user_no: int):
        """미션 캐시 무효화"""
        try:
            await self.redis_client.delete(f"mission:user:{user_no}")
            print(f"Mission cache invalidated for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error invalidating cache: {e}")
            return False
    
    # ===== DB 동기화 큐 =====
    
    async def add_to_sync_queue(self, user_no: int, mission_idx: int):
        """DB 동기화 큐에 추가"""
        try:
            sync_key = f"mission:sync:{user_no}:{mission_idx}"
            
            sync_data = {
                "user_no": user_no,
                "mission_idx": mission_idx,
                "completed_at": datetime.utcnow().isoformat()
            }
            
            await self.redis_client.setex(
                sync_key,
                600,  # 10분
                json.dumps(sync_data)
            )
            
            await self.redis_client.sadd("mission:sync_pending", f"{user_no}:{mission_idx}")
            
            print(f"Added to sync queue: user={user_no}, mission={mission_idx}")
            
        except Exception as e:
            print(f"Error adding to sync queue: {e}")
    
    async def get_sync_queue(self) -> List[Dict[str, Any]]:
        """동기화 대기 항목 조회"""
        try:
            pending = await self.redis_client.smembers("mission:sync_pending")
            
            queue = []
            for item in pending:
                item_str = item.decode() if isinstance(item, bytes) else item
                parts = item_str.split(':')
                if len(parts) != 2:
                    continue
                
                user_no, mission_idx = parts
                sync_key = f"mission:sync:{user_no}:{mission_idx}"
                sync_data = await self.redis_client.get(sync_key)
                
                if sync_data:
                    data_str = sync_data.decode() if isinstance(sync_data, bytes) else sync_data
                    queue.append(json.loads(data_str))
            
            return queue
            
        except Exception as e:
            print(f"Error getting sync queue: {e}")
            return []
    
    async def remove_from_sync_queue(self, user_no: int, mission_idx: int):
        """동기화 큐에서 제거"""
        try:
            sync_key = f"mission:sync:{user_no}:{mission_idx}"
            await self.redis_client.delete(sync_key)
            await self.redis_client.srem("mission:sync_pending", f"{user_no}:{mission_idx}")
            
            print(f"Removed from sync queue: user={user_no}, mission={mission_idx}")
            
        except Exception as e:
            print(f"Error removing from sync queue: {e}")