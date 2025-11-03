from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
import redis
from .task_types import TaskType

class BaseRedisTaskManager(ABC):
    """Redis 작업 관리의 기본 클래스 (비동기 버전)"""
    
    def __init__(self, redis_client, task_type: TaskType):
        self.redis_client = redis_client
        self.task_type = task_type
        self.queue_key = f"completion_queue:{task_type.value}"
    
    def _create_member_key(self, user_no: int, task_id: Union[int, str], sub_id: Optional[Union[int, str]] = None) -> str:
        """멤버 키 생성"""
        if sub_id is not None:
            return f"{user_no}:{task_id}:{sub_id}"
        return f"{user_no}:{task_id}"
    
    def _parse_member_key(self, member_key: str) -> Dict[str, Union[int, str]]:
        """멤버 키 파싱"""
        parts = member_key.split(':')
        result = {'user_no': int(parts[0]), 'task_id': parts[1]}
        if len(parts) > 2:
            result['sub_id'] = parts[2]
        return result
    
    # 공통 메소드들
    async def add_to_queue(self, user_no: int, task_id: Union[int, str], completion_time: datetime,
                    sub_id: Optional[Union[int, str]] = None, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """큐에 작업 추가"""
        try:
            score = completion_time.timestamp()
            member = self._create_member_key(user_no, task_id, sub_id)
            
            if metadata:
                metadata_key = f"{self.queue_key}:metadata:{member}"
                await self.redis_client.hset(metadata_key, mapping=metadata)
                await self.redis_client.expire(metadata_key, 86400)
            
            result = await self.redis_client.zadd(self.queue_key, {member: score})
            
            return result > 0
        except Exception as e:
            print(f"Error adding {self.task_type.value} to queue: {e}")
            return False
    
    async def get_completed_tasks(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 작업들 조회"""
        try:
            if current_time is None:
                current_time = datetime.utcnow()
            
            max_score = current_time.timestamp()
            completed = await self.redis_client.zrangebyscore(self.queue_key, 0, max_score, withscores=True)
            
            result = []
            for member, score in completed:
                member_str = member.decode('utf-8') if isinstance(member, bytes) else member
                parsed = self._parse_member_key(member_str)
                
                metadata_key = f"{self.queue_key}:metadata:{member_str}"
                metadata = await self.redis_client.hgetall(metadata_key)
                
                if metadata:
                    metadata = {
                    k.decode('utf-8') if isinstance(k, bytes) else k:  # 키(k)가 bytes일 때만 디코딩
                    v.decode('utf-8') if isinstance(v, bytes) else v   # 값(v)이 bytes일 때만 디코딩
                    for k, v in metadata.items()
                }
                
                task_info = {
                    'task_type': self.task_type.value,
                    'user_no': parsed['user_no'],
                    'task_id': parsed['task_id'],
                    'completion_time': datetime.fromtimestamp(score),
                    'member': member_str,
                    'metadata': metadata or {}
                }
                
                if 'sub_id' in parsed:
                    task_info['sub_id'] = parsed['sub_id']
                
                result.append(task_info)
            
            return result
        except Exception as e:
            print(f"Error getting completed {self.task_type.value}: {e}")
            return []
    
    async def remove_from_queue(self, user_no: int, task_id: Union[int, str], sub_id: Optional[Union[int, str]] = None) -> bool:
        """큐에서 작업 제거"""
        try:
            member = self._create_member_key(user_no, task_id, sub_id)
            result = await self.redis_client.zrem(self.queue_key, member)
            
            metadata_key = f"{self.queue_key}:metadata:{member}"
            await self.redis_client.delete(metadata_key)
            
            return result > 0
        except Exception as e:
            print(f"Error removing {self.task_type.value} from queue: {e}")
            return False
    
    async def update_completion_time(self, user_no: int, task_id: Union[int, str], new_completion_time: datetime,
                              sub_id: Optional[Union[int, str]] = None) -> bool:
        """완료 시간 업데이트"""
        try:
            member = self._create_member_key(user_no, task_id, sub_id)
            score = new_completion_time.timestamp()
            
            await self.redis_client.zrem(self.queue_key, member)
            result = await self.redis_client.zadd(self.queue_key, {member: score})
            return result > 0
        except Exception as e:
            print(f"Error updating {self.task_type.value} completion time: {e}")
            return False
    
    async def get_completion_time(self, user_no: int, task_id: Union[int, str], 
                           sub_id: Optional[Union[int, str]] = None) -> Optional[datetime]:
        """완료 시간 조회"""
        try:
            member = self._create_member_key(user_no, task_id, sub_id)
            score = await self.redis_client.zscore(self.queue_key, member)
            
            if score is not None:
                return datetime.fromtimestamp(score)
            return None
        except Exception as e:
            print(f"Error getting {self.task_type.value} completion time: {e}")
            return None
    
    async def get_user_tasks(self, user_no: int) -> List[Dict[str, Any]]:
        """특정 사용자의 모든 작업 조회"""
        try:
            # 해당 사용자의 작업들만 필터링
            all_tasks = await self.redis_client.zrange(self.queue_key, 0, -1, withscores=True)
            user_tasks = []
            
            for member, score in all_tasks:
                member_str = member.decode('utf-8') if isinstance(member, bytes) else member
                parsed = self._parse_member_key(member_str)
                
                if parsed['user_no'] == user_no:
                    metadata_key = f"{self.queue_key}:metadata:{member_str}"
                    metadata = await self.redis_client.hgetall(metadata_key)
                    if metadata:
                        metadata = {k.decode('utf-8'): v.decode('utf-8') for k, v in metadata.items()}
                    
                    task_info = {
                        'task_type': self.task_type.value,
                        'user_no': parsed['user_no'],
                        'task_id': parsed['task_id'],
                        'completion_time': datetime.fromtimestamp(score),
                        'metadata': metadata or {}
                    }
                    
                    if 'sub_id' in parsed:
                        task_info['sub_id'] = parsed['sub_id']
                    
                    user_tasks.append(task_info)
            
            return user_tasks
        except Exception as e:
            print(f"Error getting user {self.task_type.value} tasks: {e}")
            return []
    
    async def get_queue_status(self) -> Dict[str, int]:
        """큐 상태 조회"""
        try:
            total_count = await self.redis_client.zcard(self.queue_key)
            current_time = datetime.utcnow().timestamp()
            completed_count = await self.redis_client.zcount(self.queue_key, 0, current_time)
            pending_count = total_count - completed_count
            
            return {
                'task_type': self.task_type.value,
                'total': total_count,
                'completed': completed_count,
                'pending': pending_count
            }
        except Exception as e:
            print(f"Error getting {self.task_type.value} queue status: {e}")
            return {'task_type': self.task_type.value, 'total': 0, 'completed': 0, 'pending': 0}
    
    async def cleanup_old_entries(self, days_old: int = 7) -> int:
        """오래된 항목들 정리"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days_old)
            cutoff_timestamp = cutoff_time.timestamp()
            
            # 삭제할 항목들의 메타데이터도 함께 정리
            old_tasks = await self.redis_client.zrangebyscore(self.queue_key, 0, cutoff_timestamp)
            for member in old_tasks:
                member_str = member.decode('utf-8') if isinstance(member, bytes) else member
                metadata_key = f"{self.queue_key}:metadata:{member_str}"
                await self.redis_client.delete(metadata_key)
            
            # 오래된 항목들 제거
            removed_count = await self.redis_client.zremrangebyscore(self.queue_key, 0, cutoff_timestamp)
            return removed_count
        except Exception as e:
            print(f"Error cleaning up old {self.task_type.value} entries: {e}")
            return 0
    
    # 하위 클래스에서 구현할 추상 메소드들 (선택)
    def validate_task_data(self, task_id: Union[int, str], metadata: Optional[Dict[str, Any]] = None) -> bool:
        """작업 데이터 유효성 검증 (기본 구현)"""
        return isinstance(task_id, (int, str)) and task_id is not None