from services.system.GameDataManager import GameDataManager
from services.db_manager import DBManager
from services.redis_manager import RedisManager
from datetime import datetime, timedelta
import logging
import uuid


class BuffManager:
    """
    하이브리드 버프 관리자 (BuildingManager 패턴 적용)
    - Manager가 캐싱 주도권을 가짐 (Cache-Aside Pattern Explicit Control)
    - 영구 버프: 연구, 도감 등 타 시스템 데이터를 조합하여 Redis에 캐싱
    - 임시 버프: 생성 즉시 Redis에 반영
    """
    
    CONFIG_TYPE = 'buff'
    CACHE_TTL = 60  # 계산 결과 캐시 유효 시간 (초)
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None 
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        
        # Redis 접근 컴포넌트
        self.buff_redis = redis_manager.get_buff_manager()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no

    # ==================== 영구 버프 (Permanent Buffs) ====================
    
    async def get_permanent_buffs(self, user_no: int):
        """
        영구 버프 조회 (Cache-Aside 패턴)
        1. Redis 조회
        2. 없으면 타 시스템(연구 등)에서 데이터 복구(_reconstruct)
        3. 복구된 데이터를 Redis에 캐싱
        """
        try:
            # 1. Redis에서 먼저 조회
            buffs = await self.buff_redis.get_permanent_buffs(user_no)
            
            if buffs is not None:
                # self.logger.debug(f"Buff Cache hit for user {user_no}")
                return buffs
            
            # 2. Redis 미스: 데이터 재구축 (BuildingManager의 _load_from_db와 유사)
            self.logger.info(f"Buff Cache miss for user {user_no}. Reconstructing from sources...")
            reconstructed_buffs = await self._reconstruct_permanent_buffs(user_no)
            
            # 3. Redis에 캐싱 (Manager가 명시적으로 수행)
            if reconstructed_buffs:
                await self.buff_redis.cache_permanent_buffs(user_no, reconstructed_buffs)
                self.logger.info(f"Reconstructed and cached {len(reconstructed_buffs)} buffs for user {user_no}")
            
            return reconstructed_buffs
            
        except Exception as e:
            self.logger.error(f"Error getting permanent buffs for user {user_no}: {e}")
            return {}

    async def _reconstruct_permanent_buffs(self, user_no: int):
        """
        데이터 재구축 로직 (순수 조회만 수행, Redis 저장 안함)
        - 연구, 도감, 영웅 등 타 시스템의 데이터를 취합
        """
        reconstructed = {}
        
        try:
            # [Source 1] 연구 데이터 역추적
            research_redis = self.redis_manager.get_research_manager()
            # 연구 캐시 조회 (없으면 연구 쪽도 DB 로드하겠지만, 여기선 캐시 가정)
            all_research = await research_redis.get_cached_researches(user_no)
            
            if all_research:
                research_configs = GameDataManager.REQUIRE_CONFIGS.get('research', {})
                for res_idx_str, res_data in all_research.items():
                    res_idx = int(res_idx_str)
                    res_lv = res_data.get('building_lv', 1)
                    
                    # Config에서 buff_idx 확인
                    config = research_configs.get(res_idx, {}).get(res_lv, {})
                    buff_idx = config.get('buff_idx')
                    
                    if buff_idx:
                        field = f"research:{res_idx}:{res_lv}"
                        reconstructed[field] = str(buff_idx)
            
            # [Source 2] 추가 소스 (건물 스킨, 칭호 등) 로직이 있다면 여기에 추가
            # ...

        except Exception as e:
            self.logger.error(f"Failed to reconstruct buffs for user {user_no}: {e}")
            
        return reconstructed

    async def add_permanent_buff(self, user_no: int, source_type: str, source_id: str, buff_idx: int):
        """영구 버프 추가 (Write-Through: Redis에 즉시 반영)"""
        try:
            field = f"{source_type}:{source_id}"
            
            # 1. Redis 업데이트
            await self.buff_redis.set_permanent_buff(user_no, field, buff_idx)
            
            # 2. 계산 캐시 무효화 (값이 변했으므로)
            await self.buff_redis.invalidate_buff_calculation_cache(user_no)
            
            self.logger.info(f"Permanent buff added: user={user_no}, source={field}")
            
            return {
                "success": True,
                "message": "Permanent buff added",
                "data": {"source": field, "buff_idx": buff_idx}
            }
        except Exception as e:
            self.logger.exception(f"Error adding permanent buff: {e}")
            return {"success": False, "message": str(e)}

    async def remove_permanent_buff(self, user_no: int, source_type: str, source_id: str):
        """영구 버프 제거 (Write-Through)"""
        try:
            field = f"{source_type}:{source_id}"
            
            await self.buff_redis.del_permanent_buff(user_no, field)
            await self.buff_redis.invalidate_buff_calculation_cache(user_no)
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error removing permanent buff: {e}")
            return {"success": False, "message": str(e)}

    # ==================== 임시 버프 (Temporary Buffs) ====================
    
    async def add_temporary_buff(self, user_no: int, buff_idx: int, value: float, duration_seconds: int, source: str = None):
        """임시 버프 추가 (Write-Through)"""
        try:
            # 설정 검증
            if buff_idx not in GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE]:
                return {"success": False, "message": f"Buff {buff_idx} not found"}
            
            buff_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE][buff_idx]
            buff_id = str(uuid.uuid4())[:12]
            
            now = datetime.utcnow()
            expires_at = now + timedelta(seconds=duration_seconds)
            
            metadata = {
                'buff_idx': str(buff_idx),
                'target_type': buff_config['target_type'],
                'target_sub_type': buff_config.get('target_sub_type', ''),
                'stat_type': buff_config['stat_type'],
                'value': str(value),
                'value_type': buff_config['value_type'],
                'started_at': now.isoformat(),
                'expires_at': expires_at.isoformat(),
                'source': source or 'unknown'
            }
            
            # 1. Redis 업데이트
            await self.buff_redis.add_temp_buff_task(user_no, buff_id, metadata, duration_seconds)
            
            # 2. 계산 캐시 무효화
            await self.buff_redis.invalidate_buff_calculation_cache(user_no)
            
            return {
                "success": True, 
                "message": "Temporary buff added",
                "data": {"buff_id": buff_id, "expires_at": expires_at.isoformat()}
            }
        except Exception as e:
            self.logger.exception(f"Error adding temp buff: {e}")
            return {"success": False, "message": str(e)}

    async def get_active_temporary_buffs(self, user_no: int):
        """임시 버프 조회"""
        return await self.buff_redis.get_active_temp_buffs(user_no)

    async def remove_temporary_buff(self, user_no: int, buff_id: str):
        """임시 버프 수동 제거"""
        try:
            await self.buff_redis.remove_temp_buff(user_no, buff_id)
            await self.buff_redis.invalidate_buff_calculation_cache(user_no)
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Error removing temporary buff: {e}")
            return {"success": False, "message": str(e)}

    # ==================== 통합 버프 계산 (Calculation Logic) ====================
    async def get_all_buff_totals(self, user_no: int) -> dict:
        """
        ✅ 유저의 모든 버프를 전수 조사하여 합산표 반환 (Cache-Aside)
        Returns:
            {
                "unit:attack:infantry": 15.0,
                "unit:attack:all": 10.0,
                "resource:get:gold": 25.5,
                ...
            }
        """
        try:
            # 1. 통합 캐시 확인
            cache_key = f"user:{user_no}:all_buff_totals"
            cached_data = await self.buff_redis.cache_manager.get_data(cache_key)
            if cached_data:
                return cached_data

            # 2. 캐시 미스 시 전수 계산 시작
            self.logger.info(f"Calculating ALL buffs for user {user_no}...")
            all_totals = {}

            # 2-1. 모든 영구 버프 소스 가져오기 (복구 로직 포함)
            permanent_buffs = await self.get_permanent_buffs(user_no)
            research_configs = GameDataManager.REQUIRE_CONFIGS.get('research', {})
            buff_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})

            for source, buff_idx_str in permanent_buffs.items():
                try:
                    buff_idx = int(buff_idx_str)
                    source_parts = source.split(':')
                    source_type = source_parts[0]
                    
                    # 수치(Value) 추출
                    val = 0
                    if source_type == 'research':
                        res_idx, res_lv = int(source_parts[1]), int(source_parts[2])
                        val = research_configs.get(res_idx, {}).get(res_lv, {}).get('value', 0)
                    
                    # 버프 종류(Type) 추출 및 합산
                    b_config = buff_configs.get(buff_idx)
                    if b_config:
                        self._aggregate_buff(all_totals, b_config, val)
                except: continue

            # 2-2. 모든 활성 임시 버프 가져오기
            temporary_buffs = await self.get_active_temporary_buffs(user_no)
            for b_data in temporary_buffs:
                try:
                    val = float(b_data.get('value', 0))
                    # b_data 자체가 이미 config 내용을 담고 있음
                    self._aggregate_buff(all_totals, b_data, val)
                except: continue

            # 3. 결과 캐싱 (60초)
            await self.buff_redis.cache_manager.set_data(cache_key, all_totals, expire_time=self.CACHE_TTL)
            
            return all_totals

        except Exception as e:
            self.logger.error(f"Error getting all buff totals for user {user_no}: {e}")
            return {}

    def _aggregate_buff(self, totals: dict, config: dict, value: float):
        """딕셔너리에 버프 수치 누적 (Helper)"""
        t_type = config.get('target_type', 'unknown')
        s_type = config.get('stat_type', 'none')
        sub_type = config.get('target_sub_type', 'all') or 'all'
        
        # 키 생성 규칙: "대상:스탯:서브타입"
        key = f"{t_type}:{s_type}:{sub_type}"
        totals[key] = totals.get(key, 0.0) + value
        
    async def get_total_buffs(self, user_no: int, target_type: str, stat_type: str = None, target_sub_type: str = None):
        """
        통합 버프 계산 (Cache-Aside)
        1. 계산된 결과 캐시 확인
        2. 없으면 영구+임시 버프 데이터 가져와서(필요시 복구 포함) 계산
        3. 결과를 캐시에 저장
        """
        try:
            cache_key = self._get_cache_key(user_no, target_type, stat_type, target_sub_type)
            
            # 1. 캐시 확인
            cached_value = await self.buff_redis.get_total_buff_cache(cache_key)
            if cached_value is not None:
                return cached_value
            
            # 2. 계산 시작
            total_buff = 0.0
            
            # 2-1. 영구 버프 조회 (get_permanent_buffs가 복구 로직까지 수행)
            permanent_buffs = await self.get_permanent_buffs(user_no)
            
            for source, buff_idx_str in permanent_buffs.items():
                try:
                    buff_idx = int(buff_idx_str)
                    source_parts = source.split(':')
                    source_type = source_parts[0]
                    
                    value = 0
                    if source_type == 'research':
                        res_idx, res_lv = int(source_parts[1]), int(source_parts[2])
                        res_config = GameDataManager.REQUIRE_CONFIGS['research'].get(res_idx, {}).get(res_lv, {})
                        value = res_config.get('value', 0)
                    
                    buff_config = GameDataManager.REQUIRE_CONFIGS[self.CONFIG_TYPE].get(buff_idx, {})
                    if self._buff_matches(buff_config, target_type, stat_type, target_sub_type):
                        total_buff += value
                except: continue
            
            # 2-2. 임시 버프 조회
            temporary_buffs = await self.get_active_temporary_buffs(user_no)
            for b_data in temporary_buffs:
                if self._buff_matches_dict(b_data, target_type, stat_type, target_sub_type):
                    total_buff += float(b_data.get('value', 0))
            
            # 3. 결과 캐싱
            await self.buff_redis.set_total_buff_cache(cache_key, total_buff, self.CACHE_TTL)
            
            return total_buff
            
        except Exception as e:
            self.logger.error(f"Error calculating total buffs: {e}")
            return 0.0

    # ==================== 헬퍼 및 유틸리티 ====================

    def _get_cache_key(self, user_no, t_type, s_type, sub_type):
        return f"user:{user_no}:buff_cache:{t_type}:{s_type or 'all'}:{sub_type or 'all'}"

    def _buff_matches(self, config, t_type, s_type, sub_type):
        if not config: return False
        if config.get('target_type') != t_type: return False
        if s_type and config.get('stat_type') != s_type: return False
        if sub_type:
            target_sub = config.get('target_sub_type', 'all')
            if target_sub != 'all' and target_sub != sub_type: return False
        return True

    def _buff_matches_dict(self, data, t_type, s_type, sub_type):
        if data.get('target_type') != t_type: return False
        if s_type and data.get('stat_type') != s_type: return False
        if sub_type:
            target_sub = data.get('target_sub_type', 'all')
            if target_sub != 'all' and target_sub != sub_type: return False
        return True

    async def apply_buff_to_value(self, user_no: int, base_value: float, target_type: str, stat_type: str = None, target_sub_type: str = None):
        """기본값에 버프를 적용한 최종값 계산"""
        try:
            total_buff = await self.get_total_buffs(user_no, target_type, stat_type, target_sub_type)
            multiplier = 1 + (total_buff / 100)
            final_value = base_value * multiplier
            
            if total_buff < 0:
                final_value = max(1, int(final_value))
            else:
                final_value = int(final_value)
                
            return final_value
        except Exception as e:
            self.logger.error(f"Error applying buff: {e}")
            return base_value

    async def buff_info(self):
        """API용 전체 정보 (현재 인스턴스의 user_no 기준)"""
        user_no = self.user_no
        try:
            total_buffs = await self.get_all_total_buffs(user_no)
            permanent_buffs = await self.get_permanent_buffs(user_no)
            temporary_buffs = await self.get_active_temporary_buffs(user_no)
            
            return {"success": True, "data": {"total_buff": total_buffs, "permanent_buffs": permanent_buffs, "temporary_buffs": temporary_buffs}}
        except Exception as e:
            return {"success": False, "message": str(e)}