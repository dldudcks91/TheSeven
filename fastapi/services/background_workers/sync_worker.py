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
            missions_data[mission_idx] = json.loads(json_str)
        
        db_manager = DBManager(db_session)
        result = db_manager.get_mission_manager().bulk_upsert_missions(user_no, missions_data)
        
        if not result['success']:
            raise Exception(result['message'])