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
    """미션 관리자 - DB 검증 + Redis 캐싱"""
    
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
                self.logger.warning("Mission index not found in config, using empty index")
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
        
        related = category_index.get(target_key, [])
        
        if related:
            self.logger.debug(
                f"Found {len(related)} missions for {category}:{target_idx}"
            )
        
        return related
    
    async def get_user_mission_progress(self) -> Dict[int, Dict[str, Any]]:
        """
        유저 미션 진행 상태 조회
        
        Flow:
        1. Redis 캐시 확인
        2. 캐시 없으면: DB 조회 + 검증 + Redis 캐싱
        3. 캐시 있으면: 캐시 반환
        
        Returns:
            {
                101001: {
                    "current_value": 3,
                    "target_value": 10,
                    "is_completed": True,
                    "is_claimed": True
                }
            }
        """
        if self._cached_progress is not None:
            return self._cached_progress
        
        user_no = self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            mission_redis = self.redis_manager.get_mission_manager()
            cached_progress = await mission_redis.get_user_progress(user_no)
            
            # if cached_progress:
            #     self.logger.debug(f"Cache hit: Retrieved progress for {len(cached_progress)} missions")
            #     self._cached_progress = cached_progress
            #     return cached_progress
            
            # 2. 캐시 미스: DB + 검증 후 캐싱
            self.logger.info(f"Cache miss: Loading from DB and verifying for user {user_no}")
            
            # 2-1. DB에서 미션 이력 조회
            mission_db = self.db_manager.get_mission_manager()
            db_result = mission_db.get_user_missions(user_no)
            
            db_missions = {}
            if db_result['success']:
                db_missions = db_result['data']  # {101001: {"is_completed": True, "is_claimed": True}}
            
            # 2-2. 현재 진행도 검증 (모든 미션)
            verified_progress = await self._verify_all_missions(user_no)
            
            # 2-3. ⭐ DB 데이터와 검증 결과 병합 (비즈니스 로직)
            final_progress = self._merge_mission_data(db_missions, verified_progress)
            
            # 2-4. Redis에 최종 데이터 캐싱 (단순 저장만)
            await mission_redis.cache_user_progress(user_no, final_progress)
            
            # 2-5. 다시 조회하여 반환
            self._cached_progress = await mission_redis.get_user_progress(user_no)
            
            return self._cached_progress
            
        except Exception as e:
            self.logger.error(f"Error getting user mission progress for user {user_no}: {e}")
            self._cached_progress = {}
            return {}
    
    async def _verify_all_missions(self, user_no: int) -> Dict[int, Dict[str, Any]]:
        """
        모든 미션의 현재 진행도 검증
        
        Returns:
            {
                101001: {"current_value": 10, "target_value": 10},
                101002: {"current_value": 5, "target_value": 10}
            }
        """
        try:
            # 1. Config에서 전체 미션 목록
            all_missions_data = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE)
            
            if not all_missions_data:
                self.logger.error(f"No mission config found")
                return {}
            
            # Dict → List 변환
            if isinstance(all_missions_data, dict):
                all_missions = list(all_missions_data.values())
            elif isinstance(all_missions_data, list):
                all_missions = all_missions_data
            else:
                self.logger.error(f"Invalid mission config type: {type(all_missions_data)}")
                return {}
            
            # 2. 각 미션의 current_value 계산
            verified_progress = {}
            
            for mission in all_missions:
                if not isinstance(mission, dict):
                    continue
                
                mission_idx = mission.get('mission_idx')
                if not mission_idx:
                    continue
                
                category = mission.get('category')
                target_idx = mission.get('target_idx')
                target_value = mission.get('value', 1)
                
                # 현재값 계산
                current_value = await self._get_current_value(user_no, category, target_idx)
                
                verified_progress[mission_idx] = {
                    "current_value": current_value,
                    "target_value": target_value
                }
            
            self.logger.info(f"Verified {len(verified_progress)} missions for user {user_no}")
            return verified_progress
            
        except Exception as e:
            self.logger.error(f"Error verifying missions: {e}")
            return {}
    
    def _merge_mission_data(
        self, 
        db_missions: Dict[int, Dict[str, Any]], 
        verified_progress: Dict[int, Dict[str, Any]]
    ) -> Dict[int, Dict[str, Any]]:
        """
        DB 데이터와 검증된 진행도를 병합 (비즈니스 로직)
        
        Args:
            db_missions: {101001: {"is_completed": True, "is_claimed": True, "completed_at": "..."}}
            verified_progress: {101001: {"current_value": 10, "target_value": 10}}
        
        Returns:
            {101001: {"current_value": 10, "target_value": 10, "is_completed": True, "is_claimed": True}}
        """
        final_progress = {}
        
        for mission_idx, verified in verified_progress.items():
            # 기본 데이터 (검증 결과)
            current_value = verified.get("current_value")
            if current_value == None:
                current_value = 0
            target_value = verified.get("target_value")
            if target_value == None:
                target_value = 0
            mission_data = {
                "current_value": current_value,
                "target_value": target_value,
                "is_completed": False,
                "is_claimed": False
            }
            
            # DB에 저장된 정보가 있으면 덮어쓰기
            if mission_idx in db_missions:
                db_data = db_missions[mission_idx]
                
                if db_data.get('completed_at'):
                    mission_data['is_completed'] = True
                if db_data.get('claimed_at'):
                    mission_data['is_claimed'] = True
            
            # ⭐ 자동 완료 처리: 목표 달성했는데 DB에 완료 기록이 없으면 완료 처리
            if current_value >= target_value:
                mission_data["is_completed"] = True
            
                
            
            final_progress[mission_idx] = mission_data
        
        return final_progress
    
    async def _get_current_value(self, user_no: int, category: str, target_idx: int) -> int:
        """미션 카테고리별 현재값 조회"""
        try:
            if category == 'building':
                building_manager = self._get_building_manager()
                building_manager.user_no = user_no
                buildings = await building_manager.get_user_buildings()
                building = buildings.get(str(target_idx))
                if building:
                    return building.get('building_lv', 0)
                
            
            elif category == 'unit':
                unit_manager = self._get_unit_manager()
                unit_manager.user_no = user_no
                units = await unit_manager.get_user_units()
                
                unit = units.get(str(target_idx))
                if unit:
                    return unit.get('total', 0)
            
            elif category == 'research':
                research_manager = self._get_research_manager()
                research_manager.user_no = user_no
                researches = await research_manager.get_user_researches()
                
                # 연구는 완료 여부만 체크 (있으면 1, 없으면 0)
                research = researches.get(str(target_idx))
                if research and research.get('status') == 0:  # 완료 상태
                    return 1
            
            elif category == 'hero':
                # Hero 로직 추가 필요
                return 0
            
            else:
                self.logger.warning(f"Unknown category: {category}")
                return 0
                
        except Exception as e:
            self.logger.error(f"Error getting current value for {category}:{target_idx}: {e}")
            return 0
    
    async def mission_info(self):
        """
        미션 정보 조회 - 진행 상태만 반환
        Config는 프론트엔드가 이미 가지고 있음
        
        Response:
        {
            "success": True,
            "data": {
                101001: {"current_value": 3, "is_completed": True, "is_claimed": True},
                101002: {"current_value": 5, "is_completed": True, "is_claimed": False}
            }
        }
        """
        try:
            progress = await self.get_user_mission_progress()
            
            return {
                "success": True,
                "message": f"Retrieved progress for {len(progress)} missions",
                "data": progress
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mission info: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def mission_claim(self):
        """
        보상 수령 (기존 메서드명 유지)
        
        요구사항:
        - data: {"mission_idx": 101001}
        """
        validation = self._validate_input()
        if validation:
            return validation
        
        user_no = self.user_no
        mission_idx = self.data.get('mission_idx')
        
        try:
            # 1. Redis에서 미션 상태 확인
            mission_redis = self.redis_manager.get_mission_manager()
            mission_data = await mission_redis.get_mission_by_idx(user_no, mission_idx)
            
            if not mission_data:
                return {
                    "success": False,
                    "message": f"Mission {mission_idx} not found",
                    "data": {}
                }
            
            # 2. 완료 여부 확인
            if not mission_data.get('is_completed'):
                return {
                    "success": False,
                    "message": f"Mission {mission_idx} is not completed yet",
                    "data": {}
                }
            
            # 3. 이미 수령했는지 확인
            if mission_data.get('is_claimed'):
                return {
                    "success": False,
                    "message": f"Mission {mission_idx} reward already claimed",
                    "data": {}
                }
            
            # 4. 보상 지급
            await self._grant_rewards(mission_idx)
            
            # 5. Redis 업데이트
            await mission_redis.mark_as_claimed(user_no, mission_idx)
            
            
            # 7. 캐시 무효화
            await self.invalidate_user_mission_cache(user_no)
            
            return {
                "success": True,
                "message": f"Reward claimed successfully: {mission_idx}",
                "data": {}
            }
            
        except Exception as e:
            self.logger.error(f"Error claiming reward: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def check_building_missions(self, building_idx: int = None):
        """
        건물 업그레이드 시 미션 자동 체크
        
        Args:
            building_idx: 특정 건물 idx (None이면 전체 체크)
        """
        try:
            user_no = self.user_no
            
            if building_idx:
                # 특정 건물에 관련된 미션만 조회
                related_mission_idxs = self._get_related_missions('building', building_idx)
                
                if not related_mission_idxs:
                    return {
                        "success": True,
                        "message": f"No missions for building {building_idx}",
                        "data": {"checked": 0, "completed": 0}
                    }
                
                progress = await self.get_user_mission_progress()
                all_missions_config = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                completed_count = 0
                
                for mission_idx in related_mission_idxs:
                    if progress.get(mission_idx, {}).get('is_completed'):
                        continue
                    
                    if isinstance(all_missions_config, dict):
                        mission = all_missions_config.get(mission_idx)
                    else:
                        mission = next((m for m in all_missions_config if m.get('mission_idx') == mission_idx), None)
                    
                    if not mission:
                        continue
                    
                    target_idx = mission['target_idx']
                    target_value = mission['value']
                    
                    current_value = await self._get_current_value(user_no, 'building', target_idx)
                    
                    if current_value >= target_value:
                        await self._complete_mission(mission_idx)
                        completed_count += 1
                
                if completed_count > 0:
                    await self.invalidate_user_mission_cache(user_no)
                
                return {
                    "success": True,
                    "message": f"Checked {len(related_mission_idxs)} missions, {completed_count} completed",
                    "data": {"checked": len(related_mission_idxs), "completed": completed_count}
                }
            
            else:
                # 전체 체크 (하위 호환성)
                return await self._check_all_building_missions(user_no)
            
        except Exception as e:
            self.logger.error(f"Error checking building missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def check_unit_missions(self, unit_idx: int = None):
        """유닛 생성 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
            if unit_idx:
                related_mission_idxs = self._get_related_missions('unit', unit_idx)
                
                if not related_mission_idxs:
                    return {
                        "success": True,
                        "message": f"No missions for unit {unit_idx}",
                        "data": {"checked": 0, "completed": 0}
                    }
                
                progress = await self.get_user_mission_progress()
                all_missions_config = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                completed_count = 0
                
                for mission_idx in related_mission_idxs:
                    if progress.get(mission_idx, {}).get('is_completed'):
                        continue
                    
                    if isinstance(all_missions_config, dict):
                        mission = all_missions_config.get(mission_idx)
                    else:
                        mission = next((m for m in all_missions_config if m.get('mission_idx') == mission_idx), None)
                    
                    if not mission:
                        continue
                    
                    target_idx = mission['target_idx']
                    target_value = mission['value']
                    
                    current_value = await self._get_current_value(user_no, 'unit', target_idx)
                    
                    if current_value >= target_value:
                        await self._complete_mission(mission_idx)
                        completed_count += 1
                
                if completed_count > 0:
                    await self.invalidate_user_mission_cache(user_no)
                
                return {
                    "success": True,
                    "message": f"Checked {len(related_mission_idxs)} missions, {completed_count} completed",
                    "data": {"checked": len(related_mission_idxs), "completed": completed_count}
                }
            
            else:
                return await self._check_all_unit_missions(user_no)
            
        except Exception as e:
            self.logger.error(f"Error checking unit missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def check_research_missions(self, research_idx: int = None):
        """연구 완료 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
            if research_idx:
                related_mission_idxs = self._get_related_missions('research', research_idx)
                
                if not related_mission_idxs:
                    return {
                        "success": True,
                        "message": f"No missions for research {research_idx}",
                        "data": {"checked": 0, "completed": 0}
                    }
                
                progress = await self.get_user_mission_progress()
                all_missions_config = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                completed_count = 0
                
                for mission_idx in related_mission_idxs:
                    if progress.get(mission_idx, {}).get('is_completed'):
                        continue
                    
                    if isinstance(all_missions_config, dict):
                        mission = all_missions_config.get(mission_idx)
                    else:
                        mission = next((m for m in all_missions_config if m.get('mission_idx') == mission_idx), None)
                    
                    if not mission:
                        continue
                    
                    current_value = await self._get_current_value(user_no, 'research', research_idx)
                    
                    if current_value >= 1:
                        await self._complete_mission(mission_idx)
                        completed_count += 1
                
                if completed_count > 0:
                    await self.invalidate_user_mission_cache(user_no)
                
                return {
                    "success": True,
                    "message": f"Checked {len(related_mission_idxs)} missions, {completed_count} completed",
                    "data": {"checked": len(related_mission_idxs), "completed": completed_count}
                }
            
            else:
                return await self._check_all_research_missions(user_no)
            
        except Exception as e:
            self.logger.error(f"Error checking research missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    #-------------------- 내부 헬퍼 메서드 ---------------------------------------#
    
    async def _complete_mission(self, mission_idx: int):
        """미션 완료 처리 (자동 완료 시)"""
        try:
            user_no = self.user_no
            
            # 1. Redis 완료 처리
            mission_redis = self.redis_manager.get_mission_manager()
            await mission_redis.complete_mission(user_no, mission_idx)
            
            # 2. 보상 지급
            await self._grant_rewards(mission_idx)
            
            
            self.logger.info(f"Mission completed: user={user_no}, mission_idx={mission_idx}")
            
        except Exception as e:
            self.logger.error(f"Error completing mission: {e}")
    
    async def _grant_rewards(self, mission_idx: int):
        """보상 지급"""
        try:
            user_no = self.user_no
            
            # Config에서 보상 조회
            all_missions = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
            
            if isinstance(all_missions, dict):
                mission = all_missions.get(mission_idx)
            else:
                mission = next((m for m in all_missions if m.get('mission_idx') == mission_idx), None)
            
            if not mission or not mission.get('reward'):
                self.logger.warning(f"No rewards found for mission {mission_idx}")
                return
            
            rewards = mission['reward']
            
            # ItemManager를 통해 보상 지급
            item_manager = self._get_item_manager()
            item_manager.user_no = user_no
            
            for item_idx, quantity in rewards.items():
                item_manager.data = {"item_idx": int(item_idx), "quantity": quantity}
                await item_manager.add_item()
                
                self.logger.info(f"Granted item {item_idx}: {quantity} to user {user_no}")
            
        except Exception as e:
            self.logger.error(f"Error granting rewards: {e}")
    
    async def invalidate_user_mission_cache(self, user_no: int):
        """유저 미션 캐시 무효화"""
        try:
            mission_redis = self.redis_manager.get_mission_manager()
            await mission_redis.invalidate_cache(user_no)
            self._cached_progress = None
            
        except Exception as e:
            self.logger.error(f"Error invalidating cache: {e}")
    
    #-------------------- 여기서부터 API 메서드 ---------------------------------------#
    
    async def mission_info(self):
        """
        미션 정보 조회 - 진행 상태만 반환
        Config는 프론트엔드가 이미 가지고 있음
        
        Response:
        {
            "success": True,
            "data": {
                101001: {"current_value": 3, "is_completed": True, "is_claimed": True},
                101002: {"current_value": 5, "is_completed": True, "is_claimed": False}
            }
        }
        """
        try:
            progress = await self.get_user_mission_progress()
            
            return {
                "success": True,
                "message": f"Retrieved progress for {len(progress)} missions",
                "data": progress
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mission info: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    #-------------------- 내부 헬퍼 메서드 ---------------------------------------#
    
    def _validate_input(self):
        """공통 입력값 검증"""
        if not self._data:
            return {
                "success": False,
                "message": "Missing required data payload",
                "data": {}
            }

        mission_idx = self.data.get('mission_idx')
        if not mission_idx:
            return {
                "success": False,  
                "message": f"Missing required fields: mission_idx",  
                "data": {}
            }
        return None
    
    def _get_building_manager(self):
        """BuildingManager 인스턴스 반환"""
        from services.game.BuildingManager import BuildingManager
        return BuildingManager(self.db_manager, self.redis_manager)
    
    def _get_unit_manager(self):
        """UnitManager 인스턴스 반환"""
        from services.game.UnitManager import UnitManager
        return UnitManager(self.db_manager, self.redis_manager)
    
    def _get_research_manager(self):
        """ResearchManager 인스턴스 반환"""
        from services.game.ResearchManager import ResearchManager
        return ResearchManager(self.db_manager, self.redis_manager)
    
    def _get_item_manager(self):
        """ItemManager 인스턴스 반환"""
        from services.game.ItemManager import ItemManager
        return ItemManager(self.db_manager, self.redis_manager)
    
    # 하위 호환성을 위한 전체 체크 메서드들
    async def _check_all_building_missions(self, user_no: int):
        """전체 건물 미션 체크 (하위 호환성)"""
        # 기존 로직 유지...
        pass
    
    async def _check_all_unit_missions(self, user_no: int):
        """전체 유닛 미션 체크 (하위 호환성)"""
        pass
    
    async def _check_all_research_missions(self, user_no: int):
        """전체 연구 미션 체크 (하위 호환성)"""
        pass