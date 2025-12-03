from sqlalchemy.orm import Session
import models
from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from typing import Dict, Any, List
from datetime import datetime
import logging


class MissionManager:
    """미션 관리자 - 최소 데이터 전송"""
    
    CONFIG_TYPE = 'mission'
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        
        self._cached_progress = None
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
        미션 진행도 계산
        - Config에서 모든 미션 목록 가져오기
        - DB에서 완료 이력 가져오기
        - 각 미션의 current_value 계산
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
            
            # 3. 진행도 계산
            progress = {}
            
            for mission in all_missions:
                if not isinstance(mission, dict):
                    continue
                
                mission_idx = mission.get('mission_idx')
                if not mission_idx:
                    continue
                
                category = mission.get('category')
                target_idx = mission.get('target_idx')
                target_value = mission.get('value', 0)
                
                # 현재 진행도 계산
                current_value = 0
                if mission_idx in completed_set:
                    current_value = target_value  # 완료되면 목표값과 동일
                else:
                    # 카테고리별로 현재 값 조회
                    current_value = await self._get_current_value(
                        user_no, category, target_idx
                    )
                
                # 진행 상태 저장
                progress[mission_idx] = {
                    "current_value": current_value,
                    "is_completed": mission_idx in completed_set,
                    "is_claimed": mission_idx in completed_set  # 완료 = 수령으로 간주
                }
            
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
    
    async def check_building_missions(self):
        """건물 레벨업 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
            # 건물 카테고리 미션만 필터링
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
    
    async def check_unit_missions(self):
        """유닛 생산 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
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
    
    async def check_research_missions(self):
        """연구 완료 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
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