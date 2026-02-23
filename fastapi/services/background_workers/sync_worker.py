# workers/sync_worker.py
"""
Redis → MySQL 동기화 워커들

각 워커는 dirty flag(sync_pending:{category})를 기반으로 동작:
1. 게임 로직에서 Redis 데이터 변경 시 → sadd sync_pending:{category} {user_no}
2. 워커가 주기적으로 pending set 확인 → 세션 하나 생성
3. 해당 유저의 Redis 데이터를 MySQL에 덮어쓰기 (유저 단위 commit)
4. 성공하면 pending set에서 제거 → 주기 끝나면 세션 닫기
"""
import json
import logging
from sqlalchemy.orm import Session

from .base_worker import BaseWorker
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from database import SessionLocal


class BuildingSyncWorker(BaseWorker):
    """건물 동기화 워커 (10초 주기)"""
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='building', check_interval=10.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _sync_user(self, user_no: int, db_session: Session):
        redis_key = f"user_data:{user_no}:building"
        raw_data = await self.redis_manager.redis_client.hgetall(redis_key)
        
        if not raw_data:
            return
        
        buildings_data = {}
        for building_idx, json_str in raw_data.items():
            buildings_data[building_idx] = json.loads(json_str)
        
        db_manager = DBManager(db_session)
        result = db_manager.get_building_manager().bulk_upsert_buildings(user_no, buildings_data)
        
        if not result['success']:
            raise Exception(result['message'])


class ResearchSyncWorker(BaseWorker):
    """연구 동기화 워커 (10초 주기)"""
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='research', check_interval=10.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _sync_user(self, user_no: int, db_session: Session):
        redis_key = f"user_data:{user_no}:research"
        raw_data = await self.redis_manager.redis_client.hgetall(redis_key)
        
        if not raw_data:
            return
        
        researches_data = {}
        for research_idx, json_str in raw_data.items():
            researches_data[research_idx] = json.loads(json_str)
        
        db_manager = DBManager(db_session)
        result = db_manager.get_research_manager().bulk_upsert_researches(user_no, researches_data)
        
        if not result['success']:
            raise Exception(result['message'])


class UnitSyncWorker(BaseWorker):
    """유닛 동기화 워커 (30초 주기)"""
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='unit', check_interval=30.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _sync_user(self, user_no: int, db_session: Session):
        redis_key = f"user_data:{user_no}:unit"
        raw_data = await self.redis_manager.redis_client.hgetall(redis_key)
        
        if not raw_data:    
            return
        
        units_data = {}
        for unit_idx, json_str in raw_data.items():
            if unit_idx =="0":
                continue
            units_data[unit_idx] = json.loads(json_str)
        
        db_manager = DBManager(db_session)
        result = db_manager.get_unit_manager().bulk_upsert_units(user_no, units_data)
        
        if not result['success']:
            raise Exception(result['message'])


class ResourceSyncWorker(BaseWorker):
    """자원 동기화 워커 (60초 주기)"""
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='resources', check_interval=60.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _sync_user(self, user_no: int, db_session: Session):
        redis_key = f"user_data:{user_no}:resources"
        raw_data = await self.redis_manager.redis_client.hgetall(redis_key)
        
        if not raw_data:
            return
        
        # resources는 flat hash: {'food': '99325150', 'wood': '100000', ...}
        db_manager = DBManager(db_session)
        result = db_manager.get_resource_manager().bulk_upsert_resources(user_no, raw_data)
        
        if not result['success']:
            raise Exception(result['message'])

class ItemSyncWorker(BaseWorker):
    """아이템 동기화 워커 (60초 주기) - 변경된 item_idx만 처리"""
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='item', check_interval=60.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _process_pending(self):
        pending = await self.redis_manager.redis_client.smembers(self.sync_key)
        if not pending:
            return

        self.logger.info(f"[item] syncing {len(pending)} items")
        db_session = self._create_db_session()
        success = 0
        fail = 0

        try:
            for key in pending:
                key_str = key.decode() if isinstance(key, bytes) else key
                try:
                    user_no_str, item_idx_str = key_str.split(":")
                    user_no, item_idx = int(user_no_str), int(item_idx_str)

                    redis_key = f"user_data:{user_no}:item"
                    raw = await self.redis_manager.redis_client.hget(redis_key, str(item_idx))
                    
                    if raw:
                        item_data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                        db_manager = DBManager(db_session)
                        result = db_manager.get_item_manager().bulk_upsert_item(user_no, item_idx, item_data)
                        if not result['success']:
                            raise Exception(result['message'])

                    db_session.commit()
                    await self.redis_manager.redis_client.srem(self.sync_key, key_str)
                    success += 1
                except Exception as e:
                    db_session.rollback()
                    fail += 1
                    self.logger.error(f"[item] sync failed for {key_str}: {e}")
        finally:
            db_session.close()

        self._sync_count += success
        self._error_count += fail
        self.logger.info(f"[item] sync complete: success={success}, fail={fail}")

    async def _sync_user(self, user_no: int, db_session: Session):
        redis_key = f"user_data:{user_no}:item"
        raw_data = await self.redis_manager.redis_client.hgetall(redis_key)
        if not raw_data:
            return
        db_manager = DBManager(db_session)
        for item_idx_str, json_str in raw_data.items():
            item_data = json.loads(json_str)
            result = db_manager.get_item_manager().bulk_upsert_item(user_no, int(item_idx_str), item_data)
            if not result['success']:
                raise Exception(result['message'])
        
class MissionSyncWorker(BaseWorker):
    """미션 동기화 워커 (120초 주기)"""
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='mission', check_interval=120.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _sync_user(self, user_no: int, db_session: Session):
        redis_key = f"user_data:{user_no}:mission"
        raw_data = await self.redis_manager.redis_client.hgetall(redis_key)
        
        if not raw_data:
            return
        
        missions_data = {}
        for mission_idx, json_str in raw_data.items():
            data = json.loads(json_str)
            data['is_completed'] = 1 if data.get('is_completed') else 0
            data['is_claimed'] = 1 if data.get('is_claimed') else 0
            missions_data[mission_idx] = data
        
        db_manager = DBManager(db_session)
        result = db_manager.get_mission_manager().bulk_upsert_missions(user_no, missions_data)
        
        if not result['success']:
            raise Exception(result['message'])
        
class AllianceSyncWorker(BaseWorker):
    """
    연맹 동기화 워커 (30초 주기)
    
    sync_pending:alliance set에 alliance_id가 들어있으면
    해당 연맹의 info, members, applications, research를 한번에 DB 동기화.
    
    해산된 연맹 (Redis에 info 없음) → DB에서도 관련 데이터 전부 삭제.
    """
    
    def __init__(self, redis_manager: RedisManager):
        super().__init__(category='alliance', check_interval=30.0)
        self.redis_manager = redis_manager
    
    def _create_db_session(self) -> Session:
        return SessionLocal()
    
    async def _get_pending_users(self) -> set:
        return await self.redis_manager.redis_client.smembers(self.sync_key)
    
    async def _remove_from_pending(self, user_no: int):
        # BaseWorker 인터페이스상 user_no이지만 실제로는 alliance_id
        await self.redis_manager.redis_client.srem(self.sync_key, str(user_no))
    
    async def _sync_user(self, user_no: int, db_session: Session):
        """
        alliance_id 단위로 연맹 전체 데이터 동기화
        (BaseWorker 인터페이스상 user_no이지만 실제로는 alliance_id)
        """
        alliance_id = user_no
        alliance_redis = self.redis_manager.get_alliance_manager()
        db_manager = DBManager(db_session)
        alliance_db = db_manager.get_alliance_db_manager()
        
        # 1. 연맹 기본 정보 확인
        info = await alliance_redis.get_alliance_info(alliance_id)
        
        if not info:
            # Redis에 info가 없으면 해산된 연맹 → DB에서도 삭제
            alliance_db.delete_all_research(alliance_id)
            alliance_db.delete_all_applications(alliance_id)
            alliance_db.delete_all_members(alliance_id)
            alliance_db.delete_alliance(alliance_id)
            self.logger.info(f"[alliance] disbanded alliance {alliance_id} removed from DB")
            return
        
        # 2. 연맹 기본 정보 동기화
        alliance_db.upsert_alliance(alliance_id, info)
        
        # 3. 멤버 동기화 (전체 덮어쓰기)
        members = await alliance_redis.get_members(alliance_id)
        alliance_db.delete_all_members(alliance_id)
        for user_no_str, member_data in members.items():
            alliance_db.upsert_member(alliance_id, int(user_no_str), member_data)
        
        # 4. 가입 신청 동기화
        applications = await alliance_redis.get_applications(alliance_id)
        alliance_db.delete_all_applications(alliance_id)
        for user_no_str, app_data in applications.items():
            alliance_db.upsert_application(alliance_id, int(user_no_str), app_data)
        
        # 5. 연구 동기화
        all_research = await alliance_redis.get_all_research(alliance_id)
        if all_research:
            for research_idx_str, research_data in all_research.items():
                alliance_db.upsert_research(alliance_id, int(research_idx_str), research_data)