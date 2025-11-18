# CodexManager.py

from typing import Dict, Any, Optional
from datetime import datetime
import logging


class CodexManager:
    """통합 도감 관리 매니저 - Redis 캐싱 우선, DB 동기화"""
    
    CONFIG_TYPE = 'codex'
    
    def __init__(self, db_manager, redis_manager):
        self._user_no: int = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._cached_codex = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no
    
    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_codex = None
    
    async def update_codex(self, item_type: str, item_id: int, **kwargs):
        """도감 업데이트 (통합)"""
        try:
            user_no = self.user_no
            codex_redis = self.redis_manager.get_codex_manager()
            
            # 1. Redis에 저장
            codex_data = {
                "type": item_type,
                "completed_at": datetime.utcnow().isoformat(),
                **kwargs  # level, total_trained 등
            }
            
            await codex_redis.update_codex_item(user_no, item_type, item_id, codex_data)
            
            # 2. 메모리 캐시 무효화
            self._cached_codex = None
            
            # 3. DB 동기화 큐에 추가
            sync_data = {
                "action": "update",
                "item_type": item_type,
                "item_id": item_id,
                "data": codex_data,
                "timestamp": datetime.utcnow().isoformat()
            }
            await codex_redis.add_to_sync_queue(user_no, item_type, item_id, sync_data)
            
            self.logger.info(f"Codex updated: user_no={user_no}, type={item_type}, id={item_id}")
            
            return {
                "success": True,
                "message": "Codex updated successfully",
                "data": {}
            }
            
        except Exception as e:
            self.logger.error(f"Error updating codex: {e}")
            return {
                "success": False,
                "message": f"Error updating codex: {str(e)}",
                "data": {}
            }
    
    async def get_codex(self, item_type: str = None) -> Dict[str, Any]:
        """도감 조회 (타입 지정 가능, 없으면 전체)"""
        user_no = self.user_no
        
        # 메모리 캐시 확인
        if self._cached_codex:
            self.logger.debug(f"Memory cache hit for codex: user_no={user_no}")
            if item_type:
                return {k: v for k, v in self._cached_codex.items() if v.get('type') == item_type}
            return self._cached_codex
        
        try:
            # 1. Redis에서 조회
            codex_redis = self.redis_manager.get_codex_manager()
            codex = await codex_redis.get_codex(user_no)
            
            if codex:
                self.logger.debug(f"Redis cache hit: Retrieved {len(codex)} items for user {user_no}")
                self._cached_codex = codex
                
                if item_type:
                    return {k: v for k, v in codex.items() if v.get('type') == item_type}
                return codex
            
            # 2. 캐시 미스: DB 조회
            codex_data = self.get_db_codex(user_no)
            
            if codex_data['success'] and codex_data['data']:
                # 3. Redis에 캐싱
                await codex_redis.cache_codex(user_no, codex_data['data'])
                self._cached_codex = codex_data['data']
                
                if item_type:
                    return {k: v for k, v in codex_data['data'].items() if v.get('type') == item_type}
                return codex_data['data']
            else:
                return {}
            
        except Exception as e:
            self.logger.error(f"Error getting codex: {e}")
            return {}
    
    def get_db_codex(self, user_no: int) -> Dict[str, Any]:
        """DB에서 도감 조회"""
        try:
            codex_db = self.db_manager.get_codex_manager()
            result = codex_db.get_codex(user_no)
            
            if not result['success']:
                return result
            
            # 데이터 포맷팅
            formatted_data = {}
            for item in result['data']:
                key = f"{item['item_type']}_{item['item_id']}"
                formatted_data[key] = {
                    'type': item['item_type'],
                    'completed_at': item.get('completed_at', ''),
                    **item.get('extra_data', {})  # level, total_trained 등
                }
            
            return {
                "success": True,
                "message": f"Loaded {len(formatted_data)} codex items from database",
                "data": formatted_data
            }
            
        except Exception as e:
            self.logger.error(f"Error loading codex from DB: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": {}
            }
    
    async def has_item(self, item_type: str, item_id: int) -> bool:
        """특정 항목 완료 여부 확인"""
        codex = await self.get_codex(item_type)
        key = f"{item_type}_{item_id}"
        return key in codex
    
    async def invalidate_cache(self):
        """캐시 무효화"""
        try:
            user_no = self.user_no
            codex_redis = self.redis_manager.get_codex_manager()
            await codex_redis.invalidate_cache(user_no)
            self._cached_codex = None
            
            self.logger.debug(f"Codex cache invalidated: user_no={user_no}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error invalidating cache: {e}")
            return False
