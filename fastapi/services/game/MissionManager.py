from sqlalchemy.orm import Session
import models

from services.system.GameDataManager import GameDataManager

from services.game import BuildingManager, ResearchManager, UnitManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from typing import Dict, Any, List
from datetime import datetime
import logging


class MissionManager:
    """미션 관리자 - DB 검증 + Redis 캐싱 (전체 상태 동기화 방식)"""
    
    CONFIG_TYPE = 'mission'
    INDEX_TYPE = 'mission_index'
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        
        self._cached_progress = None
        self._mission_index = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no
    
    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_progress = None
    
    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value
    
    def _get_mission_index(self) -> Dict[str, Dict[int, List[int]]]:
        """미션 인덱스 조회 (캐싱)"""
        if self._mission_index is not None:
            return self._mission_index
        
        try:
            self._mission_index = GameDataManager.REQUIRE_CONFIGS.get(self.INDEX_TYPE, {})
            if not self._mission_index:
                self._mission_index = {"building": {}, "unit": {}, "research": {}, "hero": {}}
            return self._mission_index
        except Exception as e:
            self.logger.error(f"Error loading mission index: {e}")
            return {"building": {}, "unit": {}, "research": {}, "hero": {}}
    
    def _get_related_missions(self, category: str, target_idx: int) -> List[int]:
        """특정 카테고리와 타겟에 관련된 미션 목록 조회"""
        index = self._get_mission_index()
        
        category_index = index.get(category, {})
        
        try:
            target_key = int(target_idx)
        except (ValueError, TypeError):
            target_key = target_idx
        return category_index.get(target_key, [])
    
    async def get_user_mission_progress(self) -> Dict[int, Dict[str, Any]]:
        """유저 미션 진행 상태 조회 (Single Source of Truth)"""
        
        
        user_no = self.user_no
        try:
            mission_redis = self.redis_manager.get_mission_manager()
            cached_progress = await mission_redis.get_user_progress(user_no)
            
            if cached_progress:
                self._cached_progress = cached_progress
                return cached_progress
            
            # 캐시 미스 시 DB + 검증 후 재캐싱
            mission_db = self.db_manager.get_mission_manager()
            db_result = mission_db.get_user_missions(user_no)
            db_missions = db_result['data'] if db_result['success'] else {}
            
            verified_progress = await self._verify_all_missions(user_no)
            final_progress = self._merge_mission_data(db_missions, verified_progress)
            
            await mission_redis.cache_user_progress(user_no, final_progress)
            self._cached_progress = await mission_redis.get_user_progress(user_no)
            return self._cached_progress
            
        except Exception as e:
            self.logger.error(f"Error getting progress for user {user_no}: {e}")
            return {}

    async def _verify_all_missions(self, user_no: int) -> Dict[int, Dict[str, Any]]:
        """전체 미션 진행도 실시간 검증"""
        try:
            all_missions_data = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
            all_missions = all_missions_data.values() if isinstance(all_missions_data, dict) else all_missions_data
            
            verified_progress = {}
            for mission in all_missions:
                m_idx = mission.get('mission_idx')
                if not m_idx: continue
                
                current_value = await self._get_current_value(user_no, mission.get('category'), mission.get('target_idx'))
                verified_progress[m_idx] = {
                    "current_value": current_value,
                    "target_value": mission.get('value', 1)
                }
            return verified_progress
        except Exception as e:
            self.logger.error(f"Error verifying missions: {e}")
            return {}

    def _merge_mission_data(self, db_missions, verified_progress):
        """DB 정보와 검증 정보를 병합"""
        final_progress = {}
        for m_idx, verified in verified_progress.items():
            curr, target = verified["current_value"], verified["target_value"]
            mission_data = {
                "current_value": curr,
                "target_value": target,
                "is_completed": curr >= target,
                "is_claimed": False
            }
            if m_idx in db_missions:
                db_data = db_missions[m_idx]
                if db_data.get('completed_at'): mission_data['is_completed'] = True
                if db_data.get('claimed_at'): mission_data['is_claimed'] = True
            final_progress[m_idx] = mission_data
        return final_progress

    async def _get_current_value(self, user_no: int, category: str, target_idx: int) -> int:
        """카테고리별 현재값 조회"""
        try:
            if category == 'building':
                mgr = self._get_building_manager()
                mgr.user_no = user_no
                data = await mgr.get_user_buildings()
                return data.get(str(target_idx), {}).get('building_lv', 0)
            elif category == 'unit':
                mgr = self._get_unit_manager()
                mgr.user_no = user_no
                data = await mgr.get_user_units()
                return data.get(str(target_idx), {}).get('total', 0)
            elif category == 'research':
                mgr = self._get_research_manager()
                mgr.user_no = user_no
                data = await mgr.get_user_researches()
                res = data.get(str(target_idx))
                return 1 if res and res.get('status') == 0 else 0
            return 0
        except Exception:
            return 0

#-------------------- API 메서드 (통합 상태 반환 구조) --------------------------#

    async def mission_info(self):
        """전체 미션 정보 조회"""
        progress = await self.get_user_mission_progress()
        return {"success": True, "data": progress}

    async def mission_claim(self):
        """보상 수령 및 갱신된 전체 상태 반환"""
        validation = self._validate_input()
        if validation: return validation
        
        user_no, mission_idx = self.user_no, self.data.get('mission_idx')
        try:
            mission_redis = self.redis_manager.get_mission_manager()
            mission_data = await mission_redis.get_mission_by_idx(user_no, mission_idx)
            
            if not mission_data or not mission_data.get('is_completed'):
                return {"success": False, "message": "Mission not completed", "data": {}}
            if mission_data.get('is_claimed'):
                return {"success": False, "message": "Already claimed", "data": {}}
            
            await self._grant_rewards(mission_idx)
            await mission_redis.mark_as_claimed(user_no, mission_idx)
            #await self.invalidate_user_mission_cache(user_no)
            if self._cached_progress and mission_idx in self._cached_progress:
                self._cached_progress[mission_idx]['is_claimed'] = True
            # 갱신된 전체 데이터 반환
            return {"success": True, "data": await self.get_user_mission_progress()}
        except Exception as e:
            return {"success": False, "message": str(e), "data": {}}

    async def check_building_missions(self, building_idx: int = None):
        """건물 관련 미션 체크 및 전체 상태 반환"""
        return await self._check_category_missions('building', building_idx)

    async def check_unit_missions(self, unit_idx: int = None):
        """유닛 관련 미션 체크 및 전체 상태 반환"""
        return await self._check_category_missions('unit', unit_idx)

    async def check_research_missions(self, research_idx: int = None):
        """연구 관련 미션 체크 및 전체 상태 반환"""
        return await self._check_category_missions('research', research_idx)

    async def _check_category_missions(self, category: str, target_idx: int = None):
        """카테고리별 미션 일괄 체크 및 결과 통합 반환"""
        try:
            user_no = self.user_no
            mission_redis = self.redis_manager.get_mission_manager()
            related_idxs = self._get_related_missions(category, target_idx) if target_idx else []
            
            config = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
            progress = await self.get_user_mission_progress()
            
            
            print("[mission_test] progress:", progress, related_idxs, target_idx)
            
            # 연관 미션이 없어도 현재 상태 반환 (정합성)
            if target_idx and not related_idxs:
                return {"success": True, "data": progress, "newly_completed": 0}

            
            updated = False
            completed_count = 0
            
            targets = related_idxs if target_idx else progress.keys()
            
            for m_idx in targets:
                #if progress.get(m_idx, {}).get('is_completed'): continue
                
                m_conf = config.get(m_idx) if isinstance(config, dict) else next((m for m in config if m.get('mission_idx') == m_idx), None)
                
                if not m_conf: continue
            
                curr = await self._get_current_value(user_no, category, m_conf['target_idx'])
                old = m_conf['value']
                if curr >= old:
                    await mission_redis.complete_mission(user_no, m_idx)
                    await mission_redis.update_mission_progress(user_no, m_idx, curr)
                    progress[m_idx]['current_value'] = curr
                    progress[m_idx]['is_completed'] = True
                    completed_count += 1
                    updated = True
                    
                elif curr != old:
                    await mission_redis.update_mission_progress(user_no, m_idx, curr)
                    progress[m_idx]['current_value'] = curr
                    updated = True
        
            
            
            # if completed_count > 0:
            #     await self.invalidate_user_mission_cache(user_no)
            
            
            return {
                "success": True,
                "data": progress,
                "newly_completed": completed_count
            }
        except Exception as e:
            self.logger.error(f"Error checking {category} missions: {e}")
            return {"success": False, "data": {}}

    async def _complete_mission(self, mission_idx: int):
        """미션 완료 처리 (Redis 업데이트)"""
        try:
            mission_redis = self.redis_manager.get_mission_manager()
            await mission_redis.complete_mission(self.user_no, mission_idx)
            #await self._grant_rewards(mission_idx)
        except Exception as e:
            self.logger.error(f"Error in _complete_mission: {e}")

    async def _grant_rewards(self, mission_idx: int):
        """보상 지급 로직"""
        all_missions = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
        mission = all_missions.get(mission_idx) if isinstance(all_missions, dict) else next((m for m in all_missions if m.get('mission_idx') == mission_idx), None)
        
        if not mission or not mission.get('reward'): return
        
        mgr = self._get_item_manager()
        mgr.user_no = self.user_no
        for item_idx, qty in mission['reward'].items():
            mgr.data = {"item_idx": int(item_idx), "quantity": qty}
            await mgr.add_item()

    async def invalidate_user_mission_cache(self, user_no: int):
        """캐시 무효화"""
        mission_redis = self.redis_manager.get_mission_manager()
        await mission_redis.invalidate_cache(user_no)
        self._cached_progress = None

    def _validate_input(self):
        if not self._data or not self.data.get('mission_idx'):
            return {"success": False, "message": "Missing mission_idx", "data": {}}
        return None
    
    # Manager Factory Methods
    def _get_building_manager(self):
        from services.game.BuildingManager import BuildingManager
        return BuildingManager(self.db_manager, self.redis_manager)
    
    def _get_unit_manager(self):
        from services.game.UnitManager import UnitManager
        return UnitManager(self.db_manager, self.redis_manager)
    
    def _get_research_manager(self):
        from services.game.ResearchManager import ResearchManager
        return ResearchManager(self.db_manager, self.redis_manager)
    
    def _get_item_manager(self):
        from services.game.ItemManager import ItemManager
        return ItemManager(self.db_manager, self.redis_manager)