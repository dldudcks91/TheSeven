from datetime import datetime
from typing import Dict, Any
import json


class MissionRedisManager:
    """미션 Redis 관리자 - user_data 구조 사용"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.cache_expire_time = 3600  # 1시간
    
    def _get_meta_key(self, user_no: int) -> str:
        """메타데이터 키 (String)"""
        return f"user_data:{user_no}:mission_meta"
    
    def _get_data_key(self, user_no: int) -> str:
        """미션 데이터 키 (Hash)"""
        return f"user_data:{user_no}:mission"
    
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
            data_key = self._get_data_key(user_no)
            
            # Hash에서 모든 미션 데이터 가져오기
            all_data = await self.redis_client.hgetall(data_key)
            
            if not all_data:
                return None
            
            # Hash 데이터 파싱
            progress = {}
            for mission_idx_bytes, data_bytes in all_data.items():
                # Bytes → String
                mission_idx_str = mission_idx_bytes.decode() if isinstance(mission_idx_bytes, bytes) else mission_idx_bytes
                data_str = data_bytes.decode() if isinstance(data_bytes, bytes) else data_bytes
                
                # JSON 파싱
                mission_data = json.loads(data_str)
                
                # Int key로 변환
                progress[int(mission_idx_str)] = mission_data
            
            print(f"[Redis] Retrieved progress for {len(progress)} missions for user {user_no}")
            return progress
            
        except Exception as e:
            print(f"[Redis] Error getting user progress: {e}")
            return None
    
    async def cache_user_progress(self, user_no: int, progress: Dict[int, Dict[str, Any]]):
        """
        사용자 미션 진행 상태 캐싱 (받은 데이터 그대로 저장)
        
        Args:
            progress: {
                101001: {"current_value": 3, "is_completed": True, "is_claimed": True}
            }
        """
        try:
            data_key = self._get_data_key(user_no)
            meta_key = self._get_meta_key(user_no)
            
            # 1. Hash에 각 미션 데이터 저장
            pipeline = self.redis_client.pipeline()
            
            for mission_idx, mission_data in progress.items():
                # mission_idx를 String으로, data를 JSON으로
                pipeline.hset(
                    data_key,
                    str(mission_idx),
                    json.dumps(mission_data)
                )
            
            # 2. Meta 정보 저장 (캐시 생성 시간)
            meta_data = {
                "cached_at": datetime.utcnow().isoformat(),
                "mission_count": len(progress)
            }
            pipeline.setex(
                meta_key,
                self.cache_expire_time,
                json.dumps(meta_data)
            )
            
            # 3. Hash에도 TTL 설정
            pipeline.expire(data_key, self.cache_expire_time)
            
            await pipeline.execute()
            
            print(f"[Redis] Cached progress for {len(progress)} missions for user {user_no}")
            return True
            
        except Exception as e:
            print(f"[Redis] Error caching progress: {e}")
            return False
    
    async def update_mission_progress(self, user_no: int, mission_idx: int, current_value: int):
        """
        미션 진행도만 업데이트 (완료 상태는 변경하지 않음)
        
        Args:
            user_no: 유저 번호
            mission_idx: 미션 인덱스
            current_value: 현재 진행값
        """
        try:
            data_key = self._get_data_key(user_no)
            
            # 1. 현재 미션 데이터 조회
            mission_data_bytes = await self.redis_client.hget(data_key, str(mission_idx))
            
            if not mission_data_bytes:
                # 캐시에 없으면 새로 생성
                mission_data = {
                    "current_value": current_value,
                    "is_completed": False,
                    "is_claimed": False
                }
            else:
                data_str = mission_data_bytes.decode() if isinstance(mission_data_bytes, bytes) else mission_data_bytes
                mission_data = json.loads(data_str)
                mission_data["current_value"] = current_value
            
            # 2. Hash 업데이트
            await self.redis_client.hset(
                data_key,
                str(mission_idx),
                json.dumps(mission_data)
            )
            
            print(f"[Redis] Updated progress for mission {mission_idx}: {current_value}")
            return True
            
        except Exception as e:
            print(f"[Redis] Error updating mission progress: {e}")
            return False
    
    async def complete_mission(self, user_no: int, mission_idx: int):
        """미션 완료 처리"""
        try:
            data_key = self._get_data_key(user_no)
            
            # 1. 현재 진행 상태 조회
            progress = await self.get_user_progress(user_no)
            
            if progress is None:
                # 캐시가 없으면 새로 생성
                progress = {}
            
            # 2. 해당 미션 완료 처리
            if mission_idx in progress:
                progress[mission_idx]['is_completed'] = True
                progress[mission_idx]['is_claimed'] = False
            else:
                # 캐시에 없으면 추가
                progress[mission_idx] = {
                    "current_value": 0,  # 완료되었으므로 목표값 달성
                    "is_completed": True,
                    "is_claimed": False,
                    "completed_at": datetime.utcnow().isoformat()
                }
            
            # 3. Hash 업데이트
            await self.redis_client.hset(
                data_key,
                str(mission_idx),
                json.dumps(progress[mission_idx])
            )
            
            print(f"[Redis] Mission {mission_idx} completed for user {user_no}")
            return True
            
        except Exception as e:
            print(f"[Redis] Error completing mission: {e}")
            return False
    
    async def mark_as_claimed(self, user_no: int, mission_idx: int):
        """보상 수령 처리 (완료와 수령을 분리하는 경우)"""
        try:
            data_key = self._get_data_key(user_no)
            
            # 1. 현재 미션 데이터 조회
            mission_data_bytes = await self.redis_client.hget(data_key, str(mission_idx))
            
            if not mission_data_bytes:
                print(f"[Redis] Mission {mission_idx} not found for user {user_no}")
                return False
            
            # 2. 데이터 파싱
            data_str = mission_data_bytes.decode() if isinstance(mission_data_bytes, bytes) else mission_data_bytes
            mission_data = json.loads(data_str)
            
            # 3. 수령 처리
            mission_data['is_claimed'] = True
            mission_data['claimed_at'] = datetime.utcnow().isoformat()
            
            # 4. Hash 업데이트
            await self.redis_client.hset(
                data_key,
                str(mission_idx),
                json.dumps(mission_data)
            )
            
            print(f"[Redis] Mission {mission_idx} claimed for user {user_no}")
            return True
            
        except Exception as e:
            print(f"[Redis] Error marking as claimed: {e}")
            return False
    
    async def is_mission_completed(self, user_no: int, mission_idx: int) -> bool:
        """미션 완료 여부 확인"""
        try:
            data_key = self._get_data_key(user_no)
            
            # Hash에서 해당 미션 조회
            mission_data_bytes = await self.redis_client.hget(data_key, str(mission_idx))
            
            if not mission_data_bytes:
                return False
            
            data_str = mission_data_bytes.decode() if isinstance(mission_data_bytes, bytes) else mission_data_bytes
            mission_data = json.loads(data_str)
            
            return mission_data.get('is_completed', False)
            
        except Exception as e:
            print(f"[Redis] Error checking mission completion: {e}")
            return False
    
    async def is_mission_claimed(self, user_no: int, mission_idx: int) -> bool:
        """보상 수령 여부 확인"""
        try:
            data_key = self._get_data_key(user_no)
            
            # Hash에서 해당 미션 조회
            mission_data_bytes = await self.redis_client.hget(data_key, str(mission_idx))
            
            if not mission_data_bytes:
                return False
            
            data_str = mission_data_bytes.decode() if isinstance(mission_data_bytes, bytes) else mission_data_bytes
            mission_data = json.loads(data_str)
            
            return mission_data.get('is_claimed', False)
            
        except Exception as e:
            print(f"[Redis] Error checking mission claim: {e}")
            return False
    
    async def invalidate_cache(self, user_no: int):
        """미션 캐시 무효화"""
        try:
            data_key = self._get_data_key(user_no)
            meta_key = self._get_meta_key(user_no)
            
            # Hash와 Meta 모두 삭제
            pipeline = self.redis_client.pipeline()
            pipeline.delete(data_key)
            pipeline.delete(meta_key)
            await pipeline.execute()
            
            print(f"[Redis] Mission cache invalidated for user {user_no}")
            return True
            
        except Exception as e:
            print(f"[Redis] Error invalidating cache: {e}")
            return False
    
    async def get_cache_meta(self, user_no: int) -> Dict[str, Any]:
        """캐시 메타 정보 조회"""
        try:
            meta_key = self._get_meta_key(user_no)
            meta_bytes = await self.redis_client.get(meta_key)
            
            if not meta_bytes:
                return None
            
            meta_str = meta_bytes.decode() if isinstance(meta_bytes, bytes) else meta_bytes
            return json.loads(meta_str)
            
        except Exception as e:
            print(f"[Redis] Error getting cache meta: {e}")
            return None
    
    # ===== 배치 업데이트 (성능 최적화) =====
    
    async def batch_update_missions(self, user_no: int, missions: Dict[int, Dict[str, Any]]):
        """
        여러 미션을 배치로 업데이트 (성능 최적화)
        
        Args:
            missions: {
                101001: {"current_value": 10, "is_completed": True, "is_claimed": False},
                101002: {"current_value": 5, "is_completed": False, "is_claimed": False}
            }
        """
        try:
            data_key = self._get_data_key(user_no)
            
            # Pipeline으로 배치 처리
            pipeline = self.redis_client.pipeline()
            
            for mission_idx, mission_data in missions.items():
                pipeline.hset(
                    data_key,
                    str(mission_idx),
                    json.dumps(mission_data)
                )
            
            # TTL 갱신
            pipeline.expire(data_key, self.cache_expire_time)
            
            await pipeline.execute()
            
            print(f"[Redis] Batch updated {len(missions)} missions for user {user_no}")
            return True
            
        except Exception as e:
            print(f"[Redis] Error batch updating missions: {e}")
            return False
    
    async def get_mission_by_idx(self, user_no: int, mission_idx: int) -> Dict[str, Any]:
        """특정 미션 하나만 조회 (성능 최적화)"""
        try:
            data_key = self._get_data_key(user_no)
            
            mission_data_bytes = await self.redis_client.hget(data_key, str(mission_idx))
            
            if not mission_data_bytes:
                return None
            
            data_str = mission_data_bytes.decode() if isinstance(mission_data_bytes, bytes) else mission_data_bytes
            return json.loads(data_str)
            
        except Exception as e:
            print(f"[Redis] Error getting mission {mission_idx}: {e}")
            return None