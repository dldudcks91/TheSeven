from sqlalchemy.orm import Session
import models
from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from typing import Dict, Any, List
from datetime import datetime
import logging


class MissionManager:
    """미션 관리자 - 인덱스 기반 최적화"""
    
    CONFIG_TYPE = 'mission'
    INDEX_TYPE = 'mission_index'  # Config에 추가할 인덱스
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        
        self._cached_progress = None
        self._mission_index = None  # 인덱스 캐시
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
    
    def _get_mission_index(self) -> Dict[str, Dict[int, List[int]]]:
        """
        미션 인덱스 조회 (캐싱)
        
        Returns:
            {
                "building": {201: [101001, 101002], 202: [101003]},
                "unit": {401: [102001, 102002]},
                "research": {1001: [103001]}
            }
        """
        if self._mission_index is not None:
            return self._mission_index
        
        try:
            # Config에서 인덱스 로드
            self._mission_index = GameDataManager.REQUIRE_CONFIGS.get(self.INDEX_TYPE, {})
            
            if not self._mission_index:
                self.logger.warning("Mission index not found in config, using empty index")
                self._mission_index = {"building": {}, "unit": {}, "research": {}, "hero": {}}
            
            return self._mission_index
            
        except Exception as e:
            self.logger.error(f"Error loading mission index: {e}")
            return {"building": {}, "unit": {}, "research": {}, "hero": {}}
    
    def _get_related_missions(self, category: str, target_idx: int) -> List[int]:
        """
        특정 카테고리와 타겟에 관련된 미션 목록 조회
        
        Args:
            category: "building", "unit", "research", "hero"
            target_idx: 건물/유닛/연구 인덱스
            
        Returns:
            [101001, 101002, 101003]  # 관련 미션 idx 리스트
        """
        index = self._get_mission_index()
        category_index = index.get(category, {})
        
        # target_idx는 string일 수도 있으니 int로 변환
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
        유저 미션 진행 상태만 조회
        Config는 프론트엔드가 이미 가지고 있음
        
        Returns:
            {
                101001: {"current_value": 3, "is_completed": True, "is_claimed": True},
                101002: {"current_value": 5, "is_completed": True, "is_claimed": False}
            }
        """
        if self._cached_progress is not None:
            return self._cached_progress
        
        user_no = self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            mission_redis = self.redis_manager.get_mission_manager()
            self._cached_progress = await mission_redis.get_user_progress(user_no)
            
            if self._cached_progress:
                self.logger.debug(f"Cache hit: Retrieved progress for {len(self._cached_progress)} missions")
                return self._cached_progress
            
            # 2. 캐시 미스: DB 조회 + 계산
            progress = await self._calculate_mission_progress(user_no)
            
            # 3. Redis에 캐싱
            if progress:
                await mission_redis.cache_user_progress(user_no, progress)
            
            self._cached_progress = progress
            
        except Exception as e:
            self.logger.error(f"Error getting user mission progress for user {user_no}: {e}")
            self._cached_progress = {}
        
        return self._cached_progress
    
    async def _calculate_mission_progress(self, user_no: int) -> Dict[int, Dict[str, Any]]:
        """
        미션 진행도 계산 + 실제 완료 여부 검증
        - Config에서 모든 미션 목록 가져오기
        - DB에서 완료 이력 가져오기
        - 각 미션의 current_value 계산
        - ⭐ 실제로 목표 달성한 미션은 자동 완료 처리
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
            
            # 2. DB에서 완료 이력 조회
            mission_db = self.db_manager.get_mission_manager()
            completed_result = mission_db.get_completed_missions(user_no)
            
            completed_set = set()
            if completed_result['success']:
                completed_set = {item['mission_idx'] for item in completed_result['data']}
            
            # 3. 진행도 계산 + 실제 완료 검증
            progress = {}
            newly_completed = []  # 새로 완료된 미션 추적
            
            for mission in all_missions:
                if not isinstance(mission, dict):
                    continue
                
                mission_idx = mission.get('mission_idx')
                if not mission_idx:
                    continue
                
                category = mission.get('category')
                target_idx = mission.get('target_idx')
                target_value = mission.get('value', 0)
                
                # 이미 DB에 완료 이력이 있는 경우
                if mission_idx in completed_set:
                    progress[mission_idx] = {
                        "current_value": target_value,
                        "is_completed": True,
                        "is_claimed": True
                    }
                    continue
                
                # 현재 진행도 조회
                current_value = await self._get_current_value(
                    user_no, category, target_idx
                )
                
                # ⭐ 핵심: 실제로 목표 달성했는지 체크
                is_actually_completed = current_value >= target_value
                
                if is_actually_completed:
                    # Redis에 없고 DB에도 없지만 실제로는 완료됨
                    # → 자동 완료 처리
                    self.logger.info(
                        f"[AUTO_COMPLETE] Mission {mission_idx} completed: "
                        f"current={current_value}, target={target_value}"
                    )
                    
                    # 완료 처리 (Redis + DB + 보상)
                    await self._complete_mission(mission_idx)
                    newly_completed.append(mission_idx)
                    
                    progress[mission_idx] = {
                        "current_value": current_value,
                        "is_completed": True,
                        "is_claimed": True
                    }
                else:
                    # 아직 미완료
                    progress[mission_idx] = {
                        "current_value": current_value,
                        "is_completed": False,
                        "is_claimed": False
                    }
            
            # 새로 완료된 미션이 있으면 로그
            if newly_completed:
                self.logger.info(
                    f"Auto-completed {len(newly_completed)} missions for user {user_no}: "
                    f"{newly_completed}"
                )
            
            return progress
            
        except Exception as e:
            self.logger.error(f"Error calculating mission progress: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {}
    
    async def _get_current_value(self, user_no: int, category: str, target_idx: int) -> int:
        """카테고리별 현재 진행도 조회"""
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
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error getting current value: {e}")
            return 0
    
    async def invalidate_user_mission_cache(self, user_no: int):
        """사용자 미션 캐시 무효화"""
        try:
            mission_redis = self.redis_manager.get_mission_manager()
            cache_invalidated = await mission_redis.invalidate_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_progress = None
            
            self.logger.debug(f"Mission cache invalidated for user {user_no}")
            return cache_invalidated
            
        except Exception as e:
            self.logger.error(f"Error invalidating mission cache: {e}")
            return False
    
    #-------------------- 여기서부터 API 관련 로직 ---------------------------------------#
    
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
    
    async def claim_reward(self):
        """보상 수령"""
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            mission_idx = self.data.get('mission_idx')
            user_no = self.user_no
            
            # 1. 진행 상태 조회
            progress = await self.get_user_mission_progress()
            mission_progress = progress.get(mission_idx)
            
            if not mission_progress:
                return {
                    "success": False,
                    "message": f"Mission not found: {mission_idx}",
                    "data": {}
                }
            
            # 2. 완료 여부 확인
            if not mission_progress['is_completed']:
                return {
                    "success": False,
                    "message": f"Mission not completed yet: {mission_idx}",
                    "data": {}
                }
            
            # 3. 이미 수령했는지 확인
            if mission_progress['is_claimed']:
                return {
                    "success": False,
                    "message": f"Reward already claimed: {mission_idx}",
                    "data": {}
                }
            
            # 4. 보상 지급
            await self._grant_rewards(mission_idx)
            
            # 5. 수령 상태 업데이트
            mission_redis = self.redis_manager.get_mission_manager()
            await mission_redis.mark_as_claimed(user_no, mission_idx)
            
            # 6. 캐시 무효화
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
        건물 레벨업 시 미션 자동 체크 (인덱스 기반 최적화)
        
        Args:
            building_idx: 특정 건물 idx (None이면 전체 체크)
        """
        try:
            user_no = self.user_no
            
            if building_idx:
                # 🔥 핵심: 특정 건물에 관련된 미션만 조회
                related_mission_idxs = self._get_related_missions('building', building_idx)
                
                if not related_mission_idxs:
                    # 관련 미션 없음 - 빠른 종료
                    return {
                        "success": True,
                        "message": f"No missions for building {building_idx}",
                        "data": {"checked": 0, "completed": 0}
                    }
                
                # Redis에서 진행 상태 조회
                progress = await self.get_user_mission_progress()
                
                # Config에서 미션 정보 조회
                all_missions_config = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                completed_count = 0
                
                # 관련 미션만 체크 (전체가 아님!)
                for mission_idx in related_mission_idxs:
                    # 이미 완료된 미션은 스킵
                    if progress.get(mission_idx, {}).get('is_completed'):
                        continue
                    
                    # Config에서 미션 정보
                    if isinstance(all_missions_config, dict):
                        mission = all_missions_config.get(mission_idx)
                    else:
                        mission = next((m for m in all_missions_config if m.get('mission_idx') == mission_idx), None)
                    
                    if not mission:
                        continue
                    
                    target_value = mission.get('value', 0)
                    
                    # 현재 건물 레벨 확인
                    current_value = await self._get_current_value(user_no, 'building', building_idx)
                    
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
                # building_idx 없으면 기존 방식 (전체 체크)
                # 하위 호환성 유지
                progress = await self.get_user_mission_progress()
                all_missions = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                if isinstance(all_missions, dict):
                    all_missions = list(all_missions.values())
                
                # 건물 미션 중 미완료만
                building_missions = [
                    m for m in all_missions
                    if isinstance(m, dict) 
                    and m.get('category') == 'building'
                    and not progress.get(m.get('mission_idx'), {}).get('is_completed')
                ]
                
                completed_count = 0
                
                for mission in building_missions:
                    mission_idx = mission['mission_idx']
                    target_idx = mission['target_idx']
                    target_value = mission['value']
                    
                    # 현재 건물 레벨 확인
                    current_value = await self._get_current_value(user_no, 'building', target_idx)
                    
                    if current_value >= target_value:
                        await self._complete_mission(mission_idx)
                        completed_count += 1
                
                if completed_count > 0:
                    await self.invalidate_user_mission_cache(user_no)
                
                return {
                    "success": True,
                    "message": f"Checked {len(building_missions)} missions, {completed_count} completed",
                    "data": {"checked": len(building_missions), "completed": completed_count}
                }
            
        except Exception as e:
            self.logger.error(f"Error checking building missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def check_unit_missions(self, unit_idx: int = None):
        """
        유닛 생산 시 미션 자동 체크 (인덱스 기반 최적화)
        
        Args:
            unit_idx: 특정 유닛 idx (None이면 전체 체크)
        """
        try:
            user_no = self.user_no
            
            if unit_idx:
                # 🔥 핵심: 특정 유닛에 관련된 미션만 조회
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
                    
                    target_value = mission.get('value', 0)
                    current_value = await self._get_current_value(user_no, 'unit', unit_idx)
                    
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
                progress = await self.get_user_mission_progress()
                all_missions = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                if isinstance(all_missions, dict):
                    all_missions = list(all_missions.values())
                
                unit_missions = [
                    m for m in all_missions
                    if isinstance(m, dict)
                    and m.get('category') == 'unit'
                    and not progress.get(m.get('mission_idx'), {}).get('is_completed')
                ]
                
                completed_count = 0
                
                for mission in unit_missions:
                    mission_idx = mission['mission_idx']
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
                    "message": f"Checked {len(unit_missions)} missions, {completed_count} completed",
                    "data": {"checked": len(unit_missions), "completed": completed_count}
                }
            
        except Exception as e:
            self.logger.error(f"Error checking unit missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def check_research_missions(self, research_idx: int = None):
        """
        연구 완료 시 미션 자동 체크 (인덱스 기반 최적화)
        
        Args:
            research_idx: 특정 연구 idx (None이면 전체 체크)
        """
        try:
            user_no = self.user_no
            
            if research_idx:
                # 🔥 핵심: 특정 연구에 관련된 미션만 조회
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
                    
                    # 연구는 완료 여부만 체크 (값 >= 1)
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
                # 전체 체크 (하위 호환성)
                progress = await self.get_user_mission_progress()
                all_missions = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE, {})
                
                if isinstance(all_missions, dict):
                    all_missions = list(all_missions.values())
                
                research_missions = [
                    m for m in all_missions
                    if isinstance(m, dict)
                    and m.get('category') == 'research'
                    and not progress.get(m.get('mission_idx'), {}).get('is_completed')
                ]
                
                completed_count = 0
                
                for mission in research_missions:
                    mission_idx = mission['mission_idx']
                    target_idx = mission['target_idx']
                    
                    current_value = await self._get_current_value(user_no, 'research', target_idx)
                    
                    if current_value >= 1:  # 연구는 완료만 체크
                        await self._complete_mission(mission_idx)
                        completed_count += 1
                
                if completed_count > 0:
                    await self.invalidate_user_mission_cache(user_no)
                
                return {
                    "success": True,
                    "message": f"Checked {len(research_missions)} missions, {completed_count} completed",
                    "data": {"checked": len(research_missions), "completed": completed_count}
                }
            
        except Exception as e:
            self.logger.error(f"Error checking research missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    #-------------------- 내부 헬퍼 메서드 ---------------------------------------#
    
    async def _complete_mission(self, mission_idx: int):
        """미션 완료 처리"""
        try:
            user_no = self.user_no
            
            # 1. Redis 완료 처리
            mission_redis = self.redis_manager.get_mission_manager()
            await mission_redis.complete_mission(user_no, mission_idx)
            
            # 2. 보상 지급
            await self._grant_rewards(mission_idx)
            
            # 3. DB 동기화 큐 추가
            await mission_redis.add_to_sync_queue(user_no, mission_idx)
            
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
    
    # ===== Manager 접근 헬퍼 =====
    
    def _get_building_manager(self):
        return self.redis_manager.get_building_manager()
    
    def _get_unit_manager(self):
        return self.redis_manager.get_unit_manager()
    
    def _get_research_manager(self):
        return self.redis_manager.get_research_manager()
    
    def _get_item_manager(self):
        return self.redis_manager.get_item_manager()