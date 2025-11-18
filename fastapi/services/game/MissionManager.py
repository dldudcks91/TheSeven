# MissionManager.py

from typing import Dict, Any, List
from datetime import datetime
import logging


class MissionManager:
    """미션 관리 매니저 - 직접 접근 방식"""
    
    CONFIG_TYPE = 'mission'
    
    def __init__(self, db_manager, redis_manager, game_data_manager):
        self._user_no: int = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.game_data_manager = game_data_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no
    
    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
    
    async def check_building_missions(self):
        """건물 완성 시 미션 체크"""
        try:
            user_no = self.user_no
            
            # 1. 활성 미션 조회 (캐시 우선)
            active_missions = await self._get_active_missions_by_category("building")
            
            if not active_missions:
                return {
                    "success": True,
                    "message": "No active building missions",
                    "data": {"checked": 0, "completed": 0}
                }
            
            # 2. 건물 데이터 직접 조회
            building_manager = self._get_building_manager()
            building_manager.user_no = user_no
            buildings = await building_manager.get_user_buildings(user_no)
            
            # 3. 미션 체크
            completed_count = await self._check_and_complete_missions(
                active_missions, 
                buildings, 
                "building"
            )
            
            self.logger.info(f"Building missions checked: user={user_no}, completed={completed_count}")
            
            return {
                "success": True,
                "message": f"Checked {len(active_missions)} missions, {completed_count} completed",
                "data": {"checked": len(active_missions), "completed": completed_count}
            }
            
        except Exception as e:
            self.logger.error(f"Error checking building missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def check_unit_missions(self):
        """유닛 훈련 시 미션 체크"""
        try:
            user_no = self.user_no
            
            # 1. 활성 미션 조회
            active_missions = await self._get_active_missions_by_category("unit")
            
            if not active_missions:
                return {
                    "success": True,
                    "message": "No active unit missions",
                    "data": {"checked": 0, "completed": 0}
                }
            
            # 2. 유닛 데이터 직접 조회
            unit_manager = self._get_unit_manager()
            unit_manager.user_no = user_no
            units = await unit_manager.get_user_units(user_no)
            
            # 3. 미션 체크
            completed_count = await self._check_and_complete_missions(
                active_missions,
                units,
                "unit"
            )
            
            self.logger.info(f"Unit missions checked: user={user_no}, completed={completed_count}")
            
            return {
                "success": True,
                "message": f"Checked {len(active_missions)} missions, {completed_count} completed",
                "data": {"checked": len(active_missions), "completed": completed_count}
            }
            
        except Exception as e:
            self.logger.error(f"Error checking unit missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def check_research_missions(self):
        """연구 완료 시 미션 체크"""
        try:
            user_no = self.user_no
            
            # 1. 활성 미션 조회
            active_missions = await self._get_active_missions_by_category("research")
            
            if not active_missions:
                return {
                    "success": True,
                    "message": "No active research missions",
                    "data": {"checked": 0, "completed": 0}
                }
            
            # 2. 연구 데이터 직접 조회
            research_manager = self._get_research_manager()
            research_manager.user_no = user_no
            researches = await research_manager.get_user_researches(user_no)
            
            # 3. 미션 체크
            completed_count = await self._check_and_complete_missions(
                active_missions,
                researches,
                "research"
            )
            
            self.logger.info(f"Research missions checked: user={user_no}, completed={completed_count}")
            
            return {
                "success": True,
                "message": f"Checked {len(active_missions)} missions, {completed_count} completed",
                "data": {"checked": len(active_missions), "completed": completed_count}
            }
            
        except Exception as e:
            self.logger.error(f"Error checking research missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": {"checked": 0, "completed": 0}
            }
    
    async def _get_active_missions_by_category(self, category: str) -> List[Dict[str, Any]]:
        """카테고리별 활성 미션 조회"""
        try:
            user_no = self.user_no
            
            # 1. 전체 미션 조회 (캐시 우선)
            missions = await self._get_user_missions()
            
            # 2. 카테고리 필터링 + 미완료만
            active = [
                m for m in missions 
                if m['category'] == category and not m['completed']
            ]
            
            return active
            
        except Exception as e:
            self.logger.error(f"Error getting active missions: {e}")
            return []
    
    async def _check_and_complete_missions(
        self, 
        missions: List[Dict[str, Any]], 
        user_data: Dict[str, Any],
        category: str
    ) -> int:
        """미션 조건 체크 및 완료 처리"""
        completed_count = 0
        
        for mission in missions:
            if self._check_mission_condition(mission, user_data, category):
                await self._complete_mission(mission['mission_idx'])
                completed_count += 1
        
        return completed_count
    
    def _check_mission_condition(
        self, 
        mission: Dict[str, Any], 
        user_data: Dict[str, Any],
        category: str
    ) -> bool:
        """미션 조건 체크"""
        try:
            target_idx = mission['target_idx']
            value = mission['value']
            
            # target_idx가 0이면 개수만 체크
            if target_idx == 0:
                return len(user_data) >= value
            
            # 특정 항목 체크
            item = user_data.get(str(target_idx))
            
            if not item:
                return False
            
            # 카테고리별 체크
            if category == 'building':
                # level 체크
                return item.get('level', 0) >= value
            
            elif category == 'unit':
                # total_trained 체크
                return item.get('total', 0) >= value
            
            elif category == 'research':
                # 완료 여부만 체크
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking mission condition: {e}")
            return False
    
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
            
            # GameData에서 보상 조회
            rewards = self.game_data_manager.get_mission_rewards(mission_idx)
            
            if not rewards:
                self.logger.warning(f"No rewards found for mission {mission_idx}")
                return
            
            # ResourceManager를 통해 보상 지급
            resource_manager = self._get_resource_manager()
            resource_manager.user_no = user_no
            
            for reward in rewards:
                item_idx = reward['item_idx']
                value = reward['value']
                
                # item_idx로 타입 구분해서 지급
                # await resource_manager.add_item(item_idx, value)
                self.logger.info(f"Granted item {item_idx}: {value} to user {user_no}")
            
            self.logger.info(f"Rewards granted: user={user_no}, mission_idx={mission_idx}")
            
        except Exception as e:
            self.logger.error(f"Error granting rewards: {e}")
    
    async def _get_user_missions(self) -> List[Dict[str, Any]]:
        """사용자 미션 조회 (Config + 완료 이력)"""
        try:
            user_no = self.user_no
            
            # 1. Redis 조회
            mission_redis = self.redis_manager.get_mission_manager()
            missions = await mission_redis.get_user_missions(user_no)
            
            if missions:
                return missions
            
            # 2. 캐시 미스: Config + DB 조합
            all_missions = self.game_data_manager.get_all_missions()
            completed_set = await self._get_completed_mission_set()
            
            # 3. 완료 여부 추가
            missions = []
            for mission in all_missions:
                mission_copy = mission.copy()
                mission_copy['completed'] = mission['mission_idx'] in completed_set
                missions.append(mission_copy)
            
            # 4. Redis 캐싱
            await mission_redis.cache_user_missions(user_no, missions)
            
            return missions
            
        except Exception as e:
            self.logger.error(f"Error getting user missions: {e}")
            return []
    
    async def _get_completed_mission_set(self) -> set:
        """완료된 미션 인덱스 집합 조회"""
        try:
            user_no = self.user_no
            mission_db = self.db_manager.get_mission_manager()
            
            result = mission_db.get_completed_missions(user_no)
            
            if result['success']:
                return {item['mission_idx'] for item in result['data']}
            
            return set()
            
        except Exception as e:
            self.logger.error(f"Error getting completed missions: {e}")
            return set()
    
    # ===== Manager 접근 헬퍼 =====
    
    def _get_building_manager(self):
        """BuildingManager 가져오기"""
        # 실제 구현에서는 의존성 주입으로 받아옴
        return self.redis_manager.get_building_manager()
    
    def _get_unit_manager(self):
        """UnitManager 가져오기"""
        return self.redis_manager.get_unit_manager()
    
    def _get_research_manager(self):
        """ResearchManager 가져오기"""
        return self.redis_manager.get_research_manager()
    
    def _get_resource_manager(self):
        """ResourceManager 가져오기"""
        return self.redis_manager.get_resource_manager()
    
    # ===== 외부 API =====
    
    async def get_user_missions(self):
        """사용자 미션 목록 조회 (API용)"""
        try:
            missions = await self._get_user_missions()
            
            return {
                "success": True,
                "message": f"Retrieved {len(missions)} missions",
                "data": missions
            }
            
        except Exception as e:
            self.logger.error(f"Error getting missions: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "data": []
            }