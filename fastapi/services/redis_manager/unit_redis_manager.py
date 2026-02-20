from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from .base_redis_task_manager import BaseRedisTaskManager
from .base_redis_cache_manager import BaseRedisCacheManager
from .redis_types import CacheType, TaskType
import json


class UnitRedisManager:
    """유닛 전용 Redis 관리자 - Task Manager와 Cache Manager 컴포넌트 조합 (비동기 버전)"""
    
    def __init__(self, redis_client):
        # 두 개의 매니저 컴포넌트 초기화
        self.task_manager = BaseRedisTaskManager(redis_client, TaskType.UNIT_TRAINING)
        self.cache_manager = BaseRedisCacheManager(redis_client, CacheType.UNIT)
        self.redis_client = redis_client  # 직접 접근용
        
        self.cache_expire_time = 3600  # 1시간
        
    
    def validate_task_data(self, unit_idx: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """유닛 데이터 유효성 검증"""
        if not isinstance(unit_idx, int) or unit_idx <= 0:
            return False
        if metadata and 'quantity' in metadata:
            try:
                count = int(metadata['quantity'])
                return count > 0
            except (ValueError, TypeError):
                return False
        return True
    
    # === Task Manager 위임 메서드들 ===
    async def add_unit_to_queue(self, user_no: int, unit_type: int, unit_idx: int, completion_time: datetime, 
                                sub_id: Optional[int] = None, quantity: int = 1, 
                                task_type: int = 0, target_unit_idx: Optional[int] = None) -> bool:
        """유닛을 완료 큐에 추가"""
        # metadata에 조회 시 필요한 모든 데이터를 미리 저장
        metadata = {
            # 모든 숫자를 str로 명시적 변환하여 저장 함수에 전달 (Redis Hash 값은 str이 일반적이므로)
            'user_no': str(user_no),
            'unit_type': str(unit_type),
            'unit_idx': str(unit_idx),
            'task_type': str(task_type),
            'quantity': str(quantity),
            
            
            # 시간을 타임스탬프 (float)로 변환하거나, 문자열로 유지
            'added_at': datetime.utcnow().timestamp() # (더 좋음)
        }
        
        # (선택적) 타겟 유닛도 문자열로 변환
        if target_unit_idx is not None:
            metadata['target_unit_idx'] = str(target_unit_idx)
        
        
        return await self.task_manager.add_to_queue(user_no = user_no, task_id = unit_type, completion_time = completion_time, sub_id = unit_idx, metadata = metadata)
    
    async def remove_unit(self, user_no: int, unit_type: int, unit_idx: Optional[int] = None) -> bool:
        """유닛을 완료 큐에서 제거"""
        return await self.task_manager.remove_from_queue(user_no, unit_type, unit_idx)
    
    async def get_unit_completion_time(self, user_no: int, unit_type: int, unit_idx: Optional[int] = None) -> Optional[datetime]:
        """유닛 완료 시간 조회"""
        return await self.task_manager.get_completion_time(user_no, unit_type, unit_idx)
    
    async def update_unit_completion_time(self, user_no: int, unit_idx: int, new_completion_time: datetime, 
                                         queue_id: Optional[int] = None) -> bool:
        """유닛 완료 시간 업데이트"""
        return await self.task_manager.update_completion_time(user_no, unit_idx, new_completion_time, queue_id)
    
    async def get_completed_tasks(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """완료된 유닛들 조회"""
        return await self.task_manager.get_completed_tasks(current_time)
    
    async def speedup_unit(self, user_no: int, unit_idx: int, queue_id: Optional[int] = None) -> bool:
        """유닛 즉시 완료"""
        return await self.task_manager.update_completion_time(user_no, unit_idx, datetime.utcnow(), queue_id)
    
    # === Hash 기반 캐싱 관리 메서드들 ===
    async def cache_user_units_data(self, user_no: int, units_data: Dict[str, Any]) -> bool:
        """Hash 구조로 유닛 데이터 캐싱"""
        if not units_data:
            return True
        
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self.cache_manager.get_user_data_meta_key(user_no)
            
            # 메타데이터 준비
            meta_data = {
                'cached_at': datetime.utcnow().isoformat(),
                'quantity': len(units_data),
                'user_no': user_no
            }
            
            # Cache Manager를 통해 Hash 형태로 저장
            success = await self.cache_manager.set_hash_data(
                hash_key, 
                units_data, 
                expire_time=self.cache_expire_time
            )
            
            if success:
                # 메타데이터도 저장
                await self.cache_manager.set_data(meta_key, meta_data, expire_time=self.cache_expire_time)
                print(f"Successfully cached {len(units_data)} units for user {user_no} using Hash")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error caching units data: {e}")
            return False
    
    async def get_cached_unit(self, user_no: int, unit_idx: int) -> Optional[Dict[str, Any]]:
        """특정 유닛 하나만 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            unit_data = await self.cache_manager.get_hash_field(hash_key, str(unit_idx))
            
            if unit_data:
                print(f"Cache hit: Retrieved unit {unit_idx} for user {user_no}")
                return unit_data
            
            print(f"Cache miss: Unit {unit_idx} not found for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached unit {unit_idx} for user {user_no}: {e}")
            return None
    
    async def get_cached_units(self, user_no: int) -> Optional[Dict[str, Any]]:
        """모든 유닛을 캐시에서 조회"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            units = await self.cache_manager.get_hash_data(hash_key)
            
            if units:
                print(f"Cache hit: Retrieved {len(units)} units for user {user_no}")
                return units
            
            print(f"Cache miss: No cached units for user {user_no}")
            return None
            
        except Exception as e:
            print(f"Error retrieving cached units for user {user_no}: {e}")
            return None
    
    async def update_cached_unit(self, user_no: int, unit_idx: int, unit_data: Dict[str, Any]) -> bool:
        """특정 유닛 캐시 업데이트"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            
            # Cache Manager를 통해 Hash 필드 업데이트
            success = await self.cache_manager.set_hash_field(
                hash_key, 
                str(unit_idx), 
                unit_data,
                expire_time=self.cache_expire_time
            )
            
            if success:
                await self.redis_client.sadd("sync_pending:unit",str(user_no))
                print(f"Updated cached unit {unit_idx} for user {user_no}")
            
            return success
            
        except Exception as e:
            print(f"Error updating cached unit {unit_idx} for user {user_no}: {e}")
            return False
    
    async def remove_cached_unit(self, user_no: int, unit_idx: int) -> bool:
        """특정 유닛을 캐시에서 제거"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            success = await self.cache_manager.delete_hash_field(hash_key, str(unit_idx))
            
            if success:
                print(f"Removed cached unit {unit_idx} for user {user_no}")
                
            return success
            
        except Exception as e:
            print(f"Error removing cached unit {unit_idx} for user {user_no}: {e}")
            return False
    
    async def invalidate_unit_cache(self, user_no: int) -> bool:
        """사용자 유닛 캐시 전체 무효화"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self._get_units_meta_key(user_no)
            
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
    
    async def get_cache_info(self, user_no: int) -> Dict[str, Any]:
        """캐시 정보 조회 (디버깅/모니터링용)"""
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            meta_key = self._get_units_meta_key(user_no)
            
            # Cache Manager를 통해 정보 조회
            quantity = await self.cache_manager.get_hash_length(hash_key)
            ttl = await self.cache_manager.get_ttl(hash_key)
            meta_data = await self.cache_manager.get_data(meta_key) or {}
            
            return {
                "user_no": user_no,
                "quantity": quantity,
                "ttl_seconds": ttl,
                "meta_data": meta_data,
                "cache_exists": quantity > 0
            }
            
        except Exception as e:
            print(f"Error getting cache info for user {user_no}: {e}")
            return {"user_no": user_no, "cache_exists": False, "error": str(e)}
    
    async def update_cached_unit_times(self, user_no: int, cached_units: Dict[str, Any]) -> Dict[str, Any]:
        """캐시된 유닛들의 완료 시간을 실시간 업데이트 (필요시만 사용)"""
        try:
            updated_units = cached_units.copy()
            
            for unit_idx, unit_data in updated_units.items():
                # 진행 중인 유닛들만 Task Manager에서 완료 시간 업데이트
                if unit_data.get('training', 0) > 0 or unit_data.get('upgrading', 0) > 0:
                    redis_completion_time = await self.get_unit_completion_time(
                        user_no, int(unit_idx)
                    )
                    if redis_completion_time:
                        unit_data['completion_time'] = redis_completion_time.isoformat()
                        unit_data['updated_from_redis'] = True
                        
                        # 개별 유닛 캐시도 업데이트
                        await self.update_cached_unit(user_no, int(unit_idx), unit_data)
            
            return updated_units
            
        except Exception as e:
            print(f"Error updating unit times from Redis: {e}")
            return cached_units
    
    # === 컴포넌트 접근 메서드들 (필요시 직접 접근) ===
    def get_task_manager(self) -> BaseRedisTaskManager:
        """Task Manager 컴포넌트 반환"""
        return self.task_manager
    
    def get_cache_manager(self) -> BaseRedisCacheManager:
        """Cache Manager 컴포넌트 반환"""
        return self.cache_manager
    
    # === 통합 유틸리티 메서드들 ===
    async def get_unit_status(self, user_no: int, unit_idx: int) -> Dict[str, Any]:
        """유닛의 전체 상태 조회 (캐시 + 큐 정보)"""
        try:
            # 캐시에서 기본 정보 조회
            cached_unit = await self.get_cached_unit(user_no, unit_idx)
            
            # 큐에서 완료 시간 조회
            completion_time = await self.get_unit_completion_time(user_no, unit_idx)
            
            status = {
                "unit_idx": unit_idx,
                "user_no": user_no,
                "cached_data": cached_unit,
                "completion_time": completion_time.isoformat() if completion_time else None,
                "in_queue": completion_time is not None,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            return status
            
        except Exception as e:
            print(f"Error getting unit status for {unit_idx}: {e}")
            return {
                "unit_idx": unit_idx,
                "user_no": user_no,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    # === 기존 호환성을 위한 별칭 메서드들 ===
    async def add_unit_training(self, user_no: int, unit_type: int, completion_time: datetime,
                         queue_id: Optional[int] = None, quantity: int = 1) -> bool:
        """유닛 훈련을 큐에 추가 (하위 호환성)"""
        return await self.add_unit_to_queue(user_no, unit_type, completion_time, queue_id, quantity)
    
    async def remove_unit_training(self, user_no: int, unit_type: int, queue_id: Optional[int] = None) -> bool:
        """유닛 훈련을 큐에서 제거 (하위 호환성)"""
        return await self.remove_unit(user_no, unit_type, queue_id)
    
    async def speedup_unit_training(self, user_no: int, unit_type: int, queue_id: Optional[int] = None) -> bool:
        """유닛 훈련 즉시 완료 (하위 호환성)"""
        return await self.speedup_unit(user_no, unit_type, queue_id)
    
    # ===== ✨ 워커 지원 메서드들 (추가) =====
    
    async def get_task_metadata(self, user_no: int, task_id: str, sub_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Task 상세 정보 조회 (워커용)
        
        Redis에 저장된 Task 정보를 조회합니다.
        Task는 unit:task:{task_id} 형태로 저장되어 있습니다.
        """
        try:
            if sub_id:
                task_key = f"{self.task_manager.queue_key}:metadata:{user_no}:{task_id}:{sub_id}"
            else:
                task_key = f"{self.task_manager.queue_key}:metadata:{user_no}:{task_id}"
            task_data = await self.redis_client.hgetall(task_key)
            
            if not task_data:
                return None
            
            
            # bytes를 디코드하여 반환
            decoded_data = {}
            for key, value in task_data.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                value_str = value.decode() if isinstance(value, bytes) else value
                decoded_data[key_str] = value_str
            
            # 타입 변환
            return {
                'user_no': int(decoded_data.get('user_no', 0)),
                'unit_idx': int(decoded_data.get('unit_idx', 0)),
                'quantity': int(decoded_data.get('quantity', 0)),
                'task_type': int(decoded_data.get('task_type', 0)),
                'target_unit_idx': int(decoded_data.get('target_unit_idx', 0)) if decoded_data.get('target_unit_idx') else None,
                'start_time': decoded_data.get('start_time', ''),
                'end_time': decoded_data.get('end_time', ''),
                
            }
            
        except Exception as e:
            print(f"Error getting task data for {task_id}: {e}")
            return None
    
    async def remove_from_queue(self, user_no: int, task_id: int, sub_id: int = None):
        """
        Task 삭제 (워커용)
        
        Redis에서 Task 정보를 삭제합니다.
        """
        
        await self.task_manager.remove_from_queue(user_no, task_id, sub_id)
            
            
    
   
    
    async def add_to_sync_queue(self, user_no: int, unit_idx: int, sync_data: Dict[str, Any]):
        """
        DB 동기화 큐에 추가 (워커용)
        
        완료된 작업을 DB 동기화 큐에 추가합니다.
        CacheSyncManager가 이 큐를 읽어서 DB에 반영합니다.
        """
        try:
            sync_key = f"unit:sync_queue:{user_no}:{unit_idx}"
            
            # 기존 동기화 데이터가 있으면 누적
            existing = await self.redis_client.get(sync_key)
            
            if existing:
                existing_data = json.loads(existing.decode() if isinstance(existing, bytes) else existing)
                
                # quantity 누적 (같은 유닛이 여러 번 완료될 수 있음)
                if 'quantity' in existing_data and 'quantity' in sync_data:
                    existing_data['quantity'] += sync_data['quantity']
                    sync_data = existing_data
            
            # 저장 (TTL 10분 - 다음 동기화까지 충분)
            await self.redis_client.setex(
                sync_key,
                600,  # 10분
                json.dumps(sync_data)
            )
            
            # 동기화 대기 목록에 추가 (Set)
            await self.redis_client.sadd("sync_pending:unit",str(user_no))
            
            print(f"Added to sync queue: user_no={user_no}, unit_idx={unit_idx}")
            
        except Exception as e:
            print(f"Error adding to sync queue: {e}")
    
    async def get_sync_queue(self) -> List[Dict[str, Any]]:
        """
        동기화 대기 중인 항목들 조회 (CacheSyncManager용)
        
        Returns:
            List of dicts with keys: user_no, unit_idx, data
        """
        try:
            # 동기화 대기 중인 모든 항목 조회
            pending_items = await self.redis_client.smembers("unit:sync_pending")
            
            sync_queue = []
            for item in pending_items:
                item_str = item.decode() if isinstance(item, bytes) else item
                user_no, unit_idx = item_str.split(':')
                user_no = int(user_no)
                unit_idx = int(unit_idx)
                
                sync_key = f"unit:sync_queue:{user_no}:{unit_idx}"
                sync_data = await self.redis_client.get(sync_key)
                
                if sync_data:
                    data_str = sync_data.decode() if isinstance(sync_data, bytes) else sync_data
                    data = json.loads(data_str)
                    
                    sync_queue.append({
                        'user_no': user_no,
                        'unit_idx': unit_idx,
                        'data': data
                    })
            
            return sync_queue
            
        except Exception as e:
            print(f"Error getting sync queue: {e}")
            return []
    
    async def remove_from_sync_queue(self, user_no: int, unit_idx: int):
        """
        DB 동기화 큐에서 제거 (CacheSyncManager용)
        
        동기화가 완료된 항목을 큐에서 제거합니다.
        """
        try:
            sync_key = f"unit:sync_queue:{user_no}:{unit_idx}"
            await self.redis_client.delete(sync_key)
            
            # 대기 목록에서도 제거
            await self.redis_client.srem(
                "unit:sync_pending",
                f"{user_no}:{unit_idx}"
            )
            
            print(f"Removed from sync queue: user_no={user_no}, unit_idx={unit_idx}")
            
        except Exception as e:
            print(f"Error removing from sync queue: {e}")
    
    async def increment_unit_field(self, user_no: int, unit_idx: int, field: str, amount: int):
        """
        유닛 필드 증가 (워커용)
        
        Redis 캐시에서 특정 필드의 값을 증가시킵니다.
        예: training, upgrading, ready, total 등
        """
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            field_key = f"{unit_idx}.{field}"  # "5.ready" 형태
            
            # Hash 내부의 특정 필드 증가
            current_unit = await self.get_cached_unit(user_no, unit_idx)
            
            if current_unit:
                current_unit[field] = current_unit.get(field, 0) + amount
                current_unit['cached_at'] = datetime.utcnow().isoformat()
                await self.update_cached_unit(user_no, unit_idx, current_unit)
            else:
                # 유닛이 없으면 새로 생성
                new_unit = {
                    field: amount,
                    'cached_at': datetime.utcnow().isoformat()
                }
                await self.update_cached_unit(user_no, unit_idx, new_unit)
            
            print(f"Incremented {field} by {amount} for unit {unit_idx}")
            
        except Exception as e:
            print(f"Error incrementing unit field: {e}")
    
    async def decrement_unit_field(self, user_no: int, unit_idx: int, field: str, amount: int):
        """
        유닛 필드 감소 (워커용)
        
        Redis 캐시에서 특정 필드의 값을 감소시킵니다.
        음수가 되지 않도록 처리합니다.
        """
        try:
            current_unit = await self.get_cached_unit(user_no, unit_idx)
            
            if current_unit:
                current_value = current_unit.get(field, 0)
                new_value = max(0, current_value - amount)
                current_unit[field] = new_value
                current_unit['cached_at'] = datetime.utcnow().isoformat()
                await self.update_cached_unit(user_no, unit_idx, current_unit)
                
                print(f"Decremented {field} by {amount} for unit {unit_idx} (new value: {new_value})")
            else:
                print(f"Unit {unit_idx} not found in cache, cannot decrement")
            
        except Exception as e:
            print(f"Error decrementing unit field: {e}")


    async def register_active_tasks_to_queue(self, user_no: int, units_data: dict):
        """
        로그인 시 training_end_time이 있는 유닛을 Task 큐에 재등록
        training > 0인데 training_end_time이 없으면 강제 완료 처리
        """
        print(f"[LoginManager >> Task >> Unit] Registered unit tasks for user {user_no}: {units_data}")
        try:
            registered = 0
            recovered = 0
            
            for unit_idx_str, unit_data in units_data.items():
                training = unit_data.get('training', 0)
                if training <= 0:
                    continue
                
                training_end_time_str = unit_data.get('training_end_time')
                unit_idx = int(unit_idx_str)
                

                
                # training_end_time 없음 → 강제 완료
                if not training_end_time_str or datetime.now(timezone.utc).replace(tzinfo=None) >= datetime.fromisoformat(training_end_time_str):
                    unit_data['total'] = unit_data.get('total', 0) + training
                    unit_data['ready'] = unit_data.get('ready', 0) + training
                    unit_data['training'] = 0
                    unit_data['training_end_time'] = None
                    unit_data['cached_at'] = datetime.utcnow().isoformat()
                    
                    hash_key = self.cache_manager.get_user_data_hash_key(user_no)
                    await self.cache_manager.set_hash_field(
                        hash_key, unit_idx_str, unit_data,
                        expire_time=self.cache_expire_time
                    )
                    recovered += 1
                    continue
                
                # 이미 큐에 있는지 확인
                existing = await self.get_unit_completion_time(user_no, unit_idx)
                if existing:
                    continue
                
                # 완료 시간 파싱
                try:
                    completion_time = datetime.fromisoformat(training_end_time_str)
                except (ValueError, TypeError):
                    continue
                
                # Task 큐에 등록
                quantity = unit_data.get('training', 0)
                unit_type = unit_idx
                
                await self.add_unit_to_queue(
                    user_no=user_no,
                    unit_type=unit_type,
                    unit_idx=unit_idx,
                    completion_time=completion_time,
                    quantity=quantity,
                    task_type=0
                )
                registered += 1
            
            if registered > 0:
                print(f"[Redis] Registered {registered} active unit tasks for user {user_no}")
            if recovered > 0:
                print(f"[Redis] Recovered {recovered} orphaned unit tasks for user {user_no}")
            
            return registered
            
        except Exception as e:
            print(f"[Redis] Error registering active tasks: {e}")
            return 0