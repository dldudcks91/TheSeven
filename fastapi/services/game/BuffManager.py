from services.system.GameDataManager import GameDataManager
from services.db_manager import DBManager
from services.redis_manager import RedisManager
from datetime import datetime, timedelta
import logging
import uuid
from typing import Dict, Any, List, Optional


class BuffManager:
    """
    버프 관리자
    
    저장/응답 구조:
        permanent_buffs (target_type별 분류):
            {
                "unit": {
                    "research:101_3": {
                        "buff_idx": 202, "target_type": "unit", "target_sub_type": "infantry",
                        "stat_type": "attack", "value": 5, "value_type": "percentage"
                    }
                },
                "resource": {...},
                "building": {...}
            }
        
        temporary_buffs (리스트):
            [
                {
                    "buff_id": "abc123", "buff_idx": 201, "target_type": "unit",
                    "target_sub_type": "all", "stat_type": "speed", "value": 10,
                    "value_type": "percentage", "expires_at": "...", "source": "item"
                }
            ]
        
        total_buffs (캐시 - 전체 재계산 방식):
            {"unit:attack:infantry": 15.0, "resource:get:all": 10.0, ...}
    """
    
    CONFIG_TYPE = 'buff'
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.buff_redis = redis_manager.get_buff_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 메모리 캐시
        self._cached_permanent = None
        self._cached_temporary = None
    
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._invalidate_memory_cache()

    def _invalidate_memory_cache(self):
        """메모리 캐시 무효화"""
        self._cached_permanent = None
        self._cached_temporary = None

    # ==================== 영구 버프 ====================

    async def get_permanent_buffs(self, user_no: int) -> Dict[str, Dict]:
        """
        영구 버프 전체 조회 (Cache-Aside)
        
        Returns:
            {
                "unit": {"research:101_3": {...}, ...},
                "resource": {"research:201_1": {...}, ...}
            }
        """
        if self._user_no == user_no and self._cached_permanent is not None:
            return self._cached_permanent
        
        try:
            buffs = await self.buff_redis.get_permanent_buffs(user_no)
            
            if buffs is not None:
                self._cached_permanent = buffs
                return buffs
            
            # 캐시 미스: 재구축
            self.logger.info(f"Buff cache miss for user {user_no}, reconstructing...")
            buffs = await self._reconstruct_permanent_buffs(user_no)
            
            if buffs:
                await self.buff_redis.cache_permanent_buffs(user_no, buffs)
            
            self._cached_permanent = buffs
            return buffs
            
        except Exception as e:
            self.logger.error(f"Error getting permanent buffs: {e}")
            return {}

    async def get_permanent_buffs_by_type(self, user_no: int, target_type: str) -> Dict:
        """
        특정 target_type의 영구 버프만 조회
        
        Args:
            target_type: "unit", "resource", "building" 등
        """
        all_buffs = await self.get_permanent_buffs(user_no)
        return all_buffs.get(target_type, {})

    async def _reconstruct_permanent_buffs(self, user_no: int) -> Dict[str, Dict]:
        """
        영구 버프 재구축 (타 시스템 데이터에서)
        target_type별로 분류하여 반환
        """
        result = {}
        buff_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
        
        try:
            # [Source 1] 연구
            research_redis = self.redis_manager.get_research_manager()
            all_research = await research_redis.get_cached_researches(user_no)
            
            if all_research:
                research_configs = GameDataManager.REQUIRE_CONFIGS.get('research', {})
                
                for res_idx_str, res_data in all_research.items():
                    res_idx = int(res_idx_str)
                    res_lv = res_data.get('research_lv', 1)
                    
                    config = research_configs.get(res_idx, {}).get(res_lv, {})
                    buff_idx = config.get('buff_idx')
                    value = config.get('value', 0)
                    
                    if buff_idx and buff_idx in buff_configs:
                        buff_config = buff_configs[buff_idx]
                        target_type = buff_config.get('target_type', 'unknown')
                        
                        source_key = f"research:{res_idx}_{res_lv}"
                        buff_data = {
                            "buff_idx": buff_idx,
                            "target_type": target_type,
                            "target_sub_type": buff_config.get('target_sub_type', 'all'),
                            "stat_type": buff_config.get('stat_type', ''),
                            "value": value,
                            "value_type": buff_config.get('value_type', 'percentage')
                        }
                        
                        if target_type not in result:
                            result[target_type] = {}
                        result[target_type][source_key] = buff_data
            
            # [Source 2] 칭호, 스킨 등 추가 소스
            # await self._reconstruct_title_buffs(user_no, result, buff_configs)
            
        except Exception as e:
            self.logger.error(f"Error reconstructing buffs: {e}")
        
        return result

    async def add_permanent_buff(self, user_no: int, source_type: str, source_id: str,
                                  buff_idx: int, value: float) -> Dict:
        """
        영구 버프 추가
        
        Args:
            source_type: "research", "title" 등
            source_id: "101_3", "5" 등
            buff_idx: 버프 인덱스
            value: 버프 수치
        """
        try:
            buff_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
            if buff_idx not in buff_configs:
                return {"success": False, "message": f"Buff {buff_idx} not found"}
            
            buff_config = buff_configs[buff_idx]
            target_type = buff_config.get('target_type', 'unknown')
            source_key = f"{source_type}:{source_id}"
            
            buff_data = {
                "buff_idx": buff_idx,
                "target_type": target_type,
                "target_sub_type": buff_config.get('target_sub_type', 'all'),
                "stat_type": buff_config.get('stat_type', ''),
                "value": value,
                "value_type": buff_config.get('value_type', 'percentage')
            }
            
            await self.buff_redis.set_permanent_buff(user_no, target_type, source_key, buff_data)
            await self.buff_redis.invalidate_total_buffs_cache(user_no)
            
            if self._user_no == user_no:
                self._invalidate_memory_cache()
            
            self.logger.info(f"Added permanent buff: {source_key} -> {buff_idx}")
            
            return {"success": True, "data": {"source_key": source_key, **buff_data}}
            
        except Exception as e:
            self.logger.error(f"Error adding permanent buff: {e}")
            return {"success": False, "message": str(e)}

    async def remove_permanent_buff(self, user_no: int, source_type: str, source_id: str,
                                     target_type: str) -> Dict:
        """
        영구 버프 제거
        
        Args:
            target_type: 버프의 target_type (삭제할 위치)
        """
        try:
            source_key = f"{source_type}:{source_id}"
            
            await self.buff_redis.del_permanent_buff(user_no, target_type, source_key)
            await self.buff_redis.invalidate_total_buffs_cache(user_no)
            
            if self._user_no == user_no:
                self._invalidate_memory_cache()
            
            return {"success": True}
            
        except Exception as e:
            self.logger.error(f"Error removing permanent buff: {e}")
            return {"success": False, "message": str(e)}

    # ==================== 임시 버프 ====================

    async def get_temporary_buffs(self, user_no: int) -> List[Dict]:
        """
        임시 버프 전체 조회
        
        Returns:
            [{"buff_id": "abc", "buff_idx": 201, "target_type": "unit", ...}, ...]
        """
        if self._user_no == user_no and self._cached_temporary is not None:
            return self._cached_temporary
        
        try:
            buffs = await self.buff_redis.get_temp_buffs(user_no)
            self._cached_temporary = buffs
            return buffs
            
        except Exception as e:
            self.logger.error(f"Error getting temporary buffs: {e}")
            return []

    async def get_temporary_buffs_by_type(self, user_no: int, target_type: str) -> List[Dict]:
        """특정 target_type의 임시 버프만 조회"""
        all_buffs = await self.get_temporary_buffs(user_no)
        return [b for b in all_buffs if b.get('target_type') == target_type]

    async def add_temporary_buff(self, user_no: int, buff_idx: int, value: float,
                                  duration_seconds: int, source: str = None) -> Dict:
        """
        임시 버프 추가
        
        Args:
            buff_idx: 버프 인덱스
            value: 버프 수치
            duration_seconds: 지속 시간 (초)
            source: 버프 출처 (item, skill 등)
        """
        try:
            buff_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
            if buff_idx not in buff_configs:
                return {"success": False, "message": f"Buff {buff_idx} not found"}
            
            buff_config = buff_configs[buff_idx]
            buff_id = str(uuid.uuid4())[:12]
            
            now = datetime.utcnow()
            expires_at = now + timedelta(seconds=duration_seconds)
            
            metadata = {
                "buff_idx": buff_idx,
                "target_type": buff_config.get('target_type', ''),
                "target_sub_type": buff_config.get('target_sub_type', 'all'),
                "stat_type": buff_config.get('stat_type', ''),
                "value": value,
                "value_type": buff_config.get('value_type', 'percentage'),
                "expires_at": expires_at.isoformat(),
                "source": source or 'unknown'
            }
            
            await self.buff_redis.add_temp_buff(user_no, buff_id, metadata, duration_seconds)
            await self.buff_redis.invalidate_total_buffs_cache(user_no)
            
            if self._user_no == user_no:
                self._cached_temporary = None
            
            return {
                "success": True,
                "data": {"buff_id": buff_id, **metadata}
            }
            
        except Exception as e:
            self.logger.error(f"Error adding temporary buff: {e}")
            return {"success": False, "message": str(e)}

    async def remove_temporary_buff(self, user_no: int, buff_id: str) -> Dict:
        """임시 버프 제거"""
        try:
            await self.buff_redis.remove_temp_buff(user_no, buff_id)
            await self.buff_redis.invalidate_total_buffs_cache(user_no)
            
            if self._user_no == user_no:
                self._cached_temporary = None
            
            return {"success": True}
            
        except Exception as e:
            self.logger.error(f"Error removing temporary buff: {e}")
            return {"success": False, "message": str(e)}

    # ==================== Total Buffs ====================

    async def get_total_buffs(self, user_no: int) -> Dict[str, float]:
        """
        버프 총합 조회 (Cache-Aside, 전체 재계산 방식)
        
        - 캐시 있으면 바로 반환
        - 캐시 없으면 permanent + temporary에서 전체 재계산
        - TTL 60초 후 자동 만료 → 다음 조회 시 재계산
        
        Returns:
            {"unit:attack:infantry": 15.0, "unit:attack:all": 5.0, "resource:get:all": 10.0, ...}
        """
        try:
            # 1. 캐시 확인
            cached = await self.buff_redis.get_total_buffs_cache(user_no)
            if cached is not None:
                self.logger.debug(f"Total buffs cache hit for user {user_no}")
                return cached
            
            # 2. 캐시 미스 → 전체 재계산
            self.logger.info(f"Total buffs cache miss for user {user_no}, recalculating...")
            totals = await self._calculate_total_buffs(user_no)
            
            # 3. 캐싱 (TTL 60초)
            await self.buff_redis.set_total_buffs_cache(user_no, totals)
            
            return totals
            
        except Exception as e:
            self.logger.error(f"Error getting total buffs: {e}")
            return {}

    async def get_total_buffs_by_type(self, user_no: int, target_type: str) -> Dict[str, float]:
        """
        특정 target_type의 버프 총합만 조회
        
        Args:
            target_type: "unit", "resource", "building" 등
            
        Returns:
            {"unit:attack:infantry": 15.0, "unit:attack:all": 5.0, ...}
        """
        all_totals = await self.get_total_buffs(user_no)
        
        # target_type으로 시작하는 것만 필터링
        prefix = f"{target_type}:"
        return {k: v for k, v in all_totals.items() if k.startswith(prefix)}

    async def _calculate_total_buffs(self, user_no: int) -> Dict[str, float]:
        """
        버프 총합 전체 재계산 (누적 방식 아님!)
        
        permanent_buffs + temporary_buffs 모두 순회하여 합산
        """
        totals = {}
        
        # 1. 영구 버프 합산
        permanent = await self.get_permanent_buffs(user_no)
        for target_type, buffs in permanent.items():
            for source_key, buff_data in buffs.items():
                self._add_to_totals(totals, buff_data)
        
        # 2. 임시 버프 합산
        temporary = await self.get_temporary_buffs(user_no)
        for buff_data in temporary:
            self._add_to_totals(totals, buff_data)
        
        return totals

    def _add_to_totals(self, totals: Dict[str, float], buff_data: Dict):
        """버프 수치를 totals에 누적"""
        target_type = buff_data.get('target_type', 'unknown')
        stat_type = buff_data.get('stat_type', 'none')
        sub_type = buff_data.get('target_sub_type', 'all') or 'all'
        value = buff_data.get('value', 0)
        
        key = f"{target_type}:{stat_type}:{sub_type}"
        totals[key] = totals.get(key, 0.0) + value

    async def get_buff_value(self, user_no: int, target_type: str,
                              stat_type: str, target_sub_type: str = None) -> float:
        """
        특정 조건의 버프값 조회
        
        Args:
            target_type: "unit", "resource" 등
            stat_type: "attack", "get" 등
            target_sub_type: "infantry", "all" 등 (None이면 all로 간주)
            
        Returns:
            해당 조건의 버프 합 + "all" 타입 버프도 합산
        """
        totals = await self.get_total_buffs(user_no)
        
        sub = target_sub_type or 'all'
        value = 0.0
        
        # 정확한 매칭
        key = f"{target_type}:{stat_type}:{sub}"
        value += totals.get(key, 0.0)
        
        # sub_type이 all이 아니면 all 타입도 합산
        if sub != 'all':
            all_key = f"{target_type}:{stat_type}:all"
            value += totals.get(all_key, 0.0)
        
        return value

    async def apply_buff(self, user_no: int, base_value: float, target_type: str,
                          stat_type: str, target_sub_type: str = None) -> int:
        """
        기본값에 버프 적용
        
        Args:
            base_value: 기본값
            target_type, stat_type, target_sub_type: 버프 조건
            
        Returns:
            버프 적용된 최종값 (최소 1)
        """
        try:
            buff_value = await self.get_buff_value(user_no, target_type, stat_type, target_sub_type)
            multiplier = 1 + (buff_value / 100)
            return max(1, int(base_value * multiplier))
        except Exception as e:
            self.logger.error(f"Error applying buff: {e}")
            return int(base_value)

    # ==================== API ====================

    async def buff_info(self) -> Dict:
        """
        API: 전체 버프 정보 (로그인, 버프 UI용)
        
        Returns:
            {
                "success": True,
                "data": {
                    "permanent_buffs": {
                        "unit": {"research:101_3": {...}, ...},
                        "resource": {...}
                    },
                    "temporary_buffs": [
                        {"buff_id": "abc", "buff_idx": 201, ...}
                    ],
                    "total_buffs": {"unit:attack:infantry": 15.0, ...}
                }
            }
        """
        user_no = self.user_no
        try:
            permanent = await self.get_permanent_buffs(user_no)
            temporary = await self.get_temporary_buffs(user_no)
            totals = await self.get_total_buffs(user_no)
            
            return {
                "success": True,
                "data": {
                    "permanent_buffs": permanent,
                    "temporary_buffs": temporary,
                    "total_buffs": totals
                }
            }
        except Exception as e:
            self.logger.error(f"Error in buff_info: {e}")
            return {"success": False, "message": str(e)}

    async def buff_total_info(self) -> Dict:
        """
        API: 총합만 (전투, 자원생산용)
        
        Returns:
            {
                "success": True,
                "data": {
                    "total_buffs": {"unit:attack:infantry": 15.0, ...}
                }
            }
        """
        user_no = self.user_no
        try:
            totals = await self.get_total_buffs(user_no)
            
            return {
                "success": True,
                "data": {
                    "total_buffs": totals
                }
            }
        except Exception as e:
            self.logger.error(f"Error in buff_total_info: {e}")
            return {"success": False, "message": str(e)}

    async def buff_total_by_type_info(self, target_type: str) -> Dict:
        """
        API: 특정 target_type의 총합만 (전투용 - unit만)
        
        Args:
            target_type: "unit", "resource" 등
            
        Returns:
            {
                "success": True,
                "data": {
                    "target_type": "unit",
                    "total_buffs": {"unit:attack:infantry": 15.0, ...}
                }
            }
        """
        user_no = self.user_no
        try:
            totals = await self.get_total_buffs_by_type(user_no, target_type)
            
            return {
                "success": True,
                "data": {
                    "target_type": target_type,
                    "total_buffs": totals
                }
            }
        except Exception as e:
            self.logger.error(f"Error in buff_total_by_type_info: {e}")
            return {"success": False, "message": str(e)}

    # ==================== 캐시 관리 ====================

    async def invalidate_all_cache(self, user_no: int) -> bool:
        """모든 버프 캐시 무효화"""
        try:
            await self.buff_redis.invalidate_permanent_buffs(user_no)
            await self.buff_redis.invalidate_total_buffs_cache(user_no)
            
            if self._user_no == user_no:
                self._invalidate_memory_cache()
            
            self.logger.info(f"All buff cache invalidated for user {user_no}")
            return True
        except Exception as e:
            self.logger.error(f"Error invalidating cache: {e}")
            return False

    async def get_cache_info(self, user_no: int) -> Dict:
        """캐시 정보 조회 (디버깅용)"""
        return await self.buff_redis.get_cache_info(user_no)