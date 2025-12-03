from datetime import datetime
from typing import Dict, Any
import json


class MissionRedisManager:
    """미션 Redis 관리자 - 진행 상태만 캐싱"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간
    
    async def get_user_progress(self, user_no: int) -> Dict[int, Dict[str, Any]]:
        """
        사용자 미션 진행 상태 조회
        
        Returns:
            {
                101001: {"current_value": 3, "is_completed": True, "is_claimed": True},
                101002: {"current_value": 5, "is_completed": True, "is_claimed": False}
            }
        """
        try:
            progress_data = await self.redis_client.get(f"mission:progress:{user_no}")
            
            if not progress_data:
                return None
            
            data_str = progress_data.decode() if isinstance(progress_data, bytes) else progress_data
            progress = json.loads(data_str)
            
            # String key를 int로 변환
            progress = {int(k): v for k, v in progress.items()}
            
            print(f"Retrieved progress for {len(progress)} missions for user {user_no}")
            return progress
            
        except Exception as e:
            print(f"Error getting user progress: {e}")
            return None
    
    async def cache_user_progress(self, user_no: int, progress: Dict[int, Dict[str, Any]]):
        """
        사용자 미션 진행 상태 캐싱
        
        Args:
            progress: {
                101001: {"current_value": 3, "is_completed": True, "is_claimed": True}
            }
        """
        try:
            # Int key를 string으로 변환 (JSON 호환성)
            progress_str = {str(k): v for k, v in progress.items()}
            
            await self.redis_client.setex(
                f"mission:progress:{user_no}",
                self.cache_expire_time,
                json.dumps(progress_str)
            )
            
            print(f"Cached progress for {len(progress)} missions for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error caching progress: {e}")
            return False
    
    async def complete_mission(self, user_no: int, mission_idx: int):
        """미션 완료 처리"""
        try:
            # 1. 완료된 미션 Set에 추가
            await self.redis_client.sadd(
                f"mission:completed:{user_no}",
                str(mission_idx)
            )
            
            # 2. 진행 상태 캐시 업데이트
            progress = await self.get_user_progress(user_no)
            
            if progress:
                if mission_idx in progress:
                    progress[mission_idx]['is_completed'] = True
                    progress[mission_idx]['is_claimed'] = True  # 완료 = 자동 수령
                else:
                    # 캐시에 없으면 추가
                    progress[mission_idx] = {
                        "current_value": 0,  # 완료되었으므로 목표값 달성
                        "is_completed": True,
                        "is_claimed": True
                    }
                
                await self.cache_user_progress(user_no, progress)
            
            print(f"Mission {mission_idx} completed for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error completing mission: {e}")
            return False
    
    async def mark_as_claimed(self, user_no: int, mission_idx: int):
        """보상 수령 처리 (완료와 수령을 분리하는 경우)"""
        try:
            # 1. 수령한 미션 Set에 추가
            await self.redis_client.sadd(
                f"mission:claimed:{user_no}",
                str(mission_idx)
            )
            
            # 2. 진행 상태 캐시 업데이트
            progress = await self.get_user_progress(user_no)
            
            if progress and mission_idx in progress:
                progress[mission_idx]['is_claimed'] = True
                await self.cache_user_progress(user_no, progress)
            
            print(f"Mission {mission_idx} claimed for user {user_no}")
            return True
            
        except Exception as e:
            print(f"Error marking as claimed: {e}")
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
    
    async def is_mission_claimed(self, user_no: int, mission_idx: int) -> bool:
        """보상 수령 여부 확인"""
        try:
            is_claimed = await self.redis_client.sismember(
                f"mission:claimed:{user_no}",
                str(mission_idx)
            )
            
            return bool(is_claimed)
            
        except Exception as e:
            print(f"Error checking mission claim: {e}")
            return False
    
    async def invalidate_cache(self, user_no: int):
        """미션 캐시 무효화"""
        try:
            await self.redis_client.delete(f"mission:progress:{user_no}")
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
    
    async def get_sync_queue(self):
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