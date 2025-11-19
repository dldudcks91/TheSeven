from sqlalchemy.orm import Session
import models
from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from typing import Dict, Any, List
from datetime import datetime
import logging


class MissionManager:
    """미션 관리자 - 컴포넌트 기반 구조"""
    
    CONFIG_TYPE = 'mission'
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager, game_data_manager: GameDataManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.game_data_manager = game_data_manager
        self._cached_missions = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no
    
    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no
        self._cached_missions = None
    
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
    
    def _format_mission_for_cache(self, mission_data):
        """캐시용 미션 데이터 포맷팅"""
        try:
            return {
                "mission_idx": mission_data.get('mission_idx'),
                "category": mission_data.get('category'),
                "target_idx": mission_data.get('target_idx'),
                "value": mission_data.get('value'),
                "required_missions": mission_data.get('required_missions', []),
                "english_name": mission_data.get('english_name'),
                "korean_name": mission_data.get('korean_name'),
                "completed": mission_data.get('completed', False),
                "completed_at": mission_data.get('completed_at'),
                "cached_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Error formatting mission data for cache: {e}")
            return {}
    
    async def get_user_missions(self):
        """사용자 미션 데이터를 캐시 우선으로 조회"""
        if self._cached_missions is not None:
            return self._cached_missions
        
        user_no = self.user_no
        
        try:
            # 1. Redis 캐시에서 먼저 조회
            mission_redis = self.redis_manager.get_mission_manager()
            self._cached_missions = await mission_redis.get_user_missions(user_no)
            
            if self._cached_missions:
                self.logger.debug(f"Cache hit: Retrieved {len(self._cached_missions)} missions for user {user_no}")
                return self._cached_missions
            
            # 2. 캐시 미스: Config + DB 조합
            missions_data = self.get_db_missions(user_no)
            
            if missions_data['success'] and missions_data['data']:
                # 3. Redis에 캐싱
                cache_success = await mission_redis.cache_user_missions(user_no, missions_data['data'])
                if cache_success:
                    self.logger.debug(f"Successfully cached {len(missions_data['data'])} missions for user {user_no}")
                
                self._cached_missions = missions_data['data']
            else:
                self._cached_missions = []
                
        except Exception as e:
            self.logger.error(f"Error getting user missions for user {user_no}: {e}")
            self._cached_missions = []
        
        return self._cached_missions
    
    def get_db_missions(self, user_no):
        """DB에서 미션 데이터 조회 (Config + 완료 이력)"""
        try:
            # 1. GameData에서 전체 미션 Config 조회
            all_missions = self.game_data_manager.get_all_missions()
            
            # 2. DB에서 완료된 미션 조회
            mission_db = self.db_manager.get_mission_manager()
            completed_result = mission_db.get_completed_missions(user_no)
            
            completed_set = set()
            completed_times = {}
            
            if completed_result['success']:
                for item in completed_result['data']:
                    completed_set.add(item['mission_idx'])
                    completed_times[item['mission_idx']] = item.get('completed_at')
            
            # 3. Config와 완료 이력 조합
            formatted_missions = []
            for mission in all_missions:
                mission_idx = mission['mission_idx']
                mission_data = {
                    **mission,
                    'completed': mission_idx in completed_set,
                    'completed_at': completed_times.get(mission_idx)
                }
                formatted_missions.append(self._format_mission_for_cache(mission_data))
            
            return {
                "success": True,
                "message": f"Loaded {len(formatted_missions)} missions",
                "data": formatted_missions
            }
            
        except Exception as e:
            self.logger.error(f"Error loading missions from DB for user {user_no}: {e}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}",
                "data": []
            }
    
    async def invalidate_user_mission_cache(self, user_no: int):
        """사용자 미션 캐시 무효화"""
        try:
            mission_redis = self.redis_manager.get_mission_manager()
            cache_invalidated = await mission_redis.invalidate_cache(user_no)
            
            # 메모리 캐시도 무효화
            if self._user_no == user_no:
                self._cached_missions = None
            
            self.logger.debug(f"Mission cache invalidated for user {user_no}: {cache_invalidated}")
            return cache_invalidated
            
        except Exception as e:
            self.logger.error(f"Error invalidating mission cache for user {user_no}: {e}")
            return False
    
    #-------------------- 여기서부터 API 관련 로직 ---------------------------------------#
    
    async def mission_info(self):
        """미션 정보 조회 - 전체 미션 목록"""
        try:
            missions_data = await self.get_user_missions()
            
            return {
                "success": True,
                "message": f"Retrieved {len(missions_data)} missions",
                "data": missions_data
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mission info: {e}")
            return {"success": False, "message": str(e), "data": []}
    
    async def mission_detail(self):
        """특정 미션 상세 정보 조회"""
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            mission_idx = self.data.get('mission_idx')
            user_no = self.user_no
            
            # 1. 미션 목록 조회
            missions_data = await self.get_user_missions()
            
            # 2. 특정 미션 찾기
            mission = next((m for m in missions_data if m['mission_idx'] == mission_idx), None)
            
            if not mission:
                return {
                    "success": False,
                    "message": f"Mission not found: {mission_idx}",
                    "data": {}
                }
            
            # 3. 보상 정보 추가
            rewards = self.game_data_manager.get_mission_rewards(mission_idx)
            mission['rewards'] = rewards or []
            
            return {
                "success": True,
                "message": "Mission detail retrieved",
                "data": mission
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mission detail: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def mission_available(self):
        """완료 가능한 미션 목록 조회"""
        try:
            user_no = self.user_no
            
            # 1. 전체 미션 조회
            missions_data = await self.get_user_missions()
            
            # 2. 미완료 미션만 필터링
            available_missions = [m for m in missions_data if not m['completed']]
            
            return {
                "success": True,
                "message": f"Retrieved {len(available_missions)} available missions",
                "data": available_missions
            }
            
        except Exception as e:
            self.logger.error(f"Error getting available missions: {e}")
            return {"success": False, "message": str(e), "data": []}
    
    async def mission_completed(self):
        """완료된 미션 목록 조회"""
        try:
            user_no = self.user_no
            
            # 1. 전체 미션 조회
            missions_data = await self.get_user_missions()
            
            # 2. 완료 미션만 필터링
            completed_missions = [m for m in missions_data if m['completed']]
            
            return {
                "success": True,
                "message": f"Retrieved {len(completed_missions)} completed missions",
                "data": completed_missions
            }
            
        except Exception as e:
            self.logger.error(f"Error getting completed missions: {e}")
            return {"success": False, "message": str(e), "data": []}
    
    async def mission_claim(self):
        """미션 보상 수령 (수동 완료)"""
        try:
            validation_error = self._validate_input()
            if validation_error:
                return validation_error
            
            mission_idx = self.data.get('mission_idx')
            user_no = self.user_no
            
            # 1. 미션 정보 조회
            missions_data = await self.get_user_missions()
            mission = next((m for m in missions_data if m['mission_idx'] == mission_idx), None)
            
            if not mission:
                return {
                    "success": False,
                    "message": "Mission not found",
                    "data": {}
                }
            
            # 2. 이미 완료된 미션인지 확인
            if mission['completed']:
                return {
                    "success": False,
                    "message": "Mission already completed",
                    "data": {}
                }
            
            # 3. 미션 조건 확인
            category = mission['category']
            condition_met = await self._check_mission_condition_by_category(mission, category)
            
            if not condition_met:
                return {
                    "success": False,
                    "message": "Mission condition not met",
                    "data": {}
                }
            
            # 4. 미션 완료 처리
            await self._complete_mission(mission_idx)
            
            # 5. 캐시 무효화
            await self.invalidate_user_mission_cache(user_no)
            
            return {
                "success": True,
                "message": "Mission claimed successfully",
                "data": {
                    "mission_idx": mission_idx,
                    "completed_at": datetime.utcnow().isoformat()
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error claiming mission: {e}")
            return {"success": False, "message": str(e), "data": {}}
    
    async def check_building_missions(self):
        """건물 완성 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
            # 1. 활성 미션 조회
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
            buildings = await building_manager.get_user_buildings()
            
            # 3. 미션 체크
            completed_count = await self._check_and_complete_missions(
                active_missions, 
                buildings, 
                "building"
            )
            
            # 4. 캐시 무효화 (미션 상태 변경됨)
            if completed_count > 0:
                await self.invalidate_user_mission_cache(user_no)
            
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
        """유닛 훈련 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
            active_missions = await self._get_active_missions_by_category("unit")
            
            if not active_missions:
                return {
                    "success": True,
                    "message": "No active unit missions",
                    "data": {"checked": 0, "completed": 0}
                }
            
            unit_manager = self._get_unit_manager()
            unit_manager.user_no = user_no
            units = await unit_manager.get_user_units()
            
            completed_count = await self._check_and_complete_missions(
                active_missions,
                units,
                "unit"
            )
            
            if completed_count > 0:
                await self.invalidate_user_mission_cache(user_no)
            
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
        """연구 완료 시 미션 자동 체크"""
        try:
            user_no = self.user_no
            
            active_missions = await self._get_active_missions_by_category("research")
            
            if not active_missions:
                return {
                    "success": True,
                    "message": "No active research missions",
                    "data": {"checked": 0, "completed": 0}
                }
            
            research_manager = self._get_research_manager()
            research_manager.user_no = user_no
            researches = await research_manager.get_user_researches()
            
            completed_count = await self._check_and_complete_missions(
                active_missions,
                researches,
                "research"
            )
            
            if completed_count > 0:
                await self.invalidate_user_mission_cache(user_no)
            
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
    
    #-------------------- 내부 헬퍼 메서드 ---------------------------------------#
    
    async def _get_active_missions_by_category(self, category: str) -> List[Dict[str, Any]]:
        """카테고리별 활성 미션 조회"""
        try:
            missions = await self.get_user_missions()
            
            # 카테고리 필터링 + 미완료만
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
    
    async def _check_mission_condition_by_category(self, mission: Dict[str, Any], category: str) -> bool:
        """카테고리별 미션 조건 체크 (수동 완료용)"""
        try:
            user_no = self.user_no
            
            if category == 'building':
                building_manager = self._get_building_manager()
                building_manager.user_no = user_no
                user_data = await building_manager.get_user_buildings()
            elif category == 'unit':
                unit_manager = self._get_unit_manager()
                unit_manager.user_no = user_no
                user_data = await unit_manager.get_user_units()
            elif category == 'research':
                research_manager = self._get_research_manager()
                research_manager.user_no = user_no
                user_data = await research_manager.get_user_researches()
            else:
                return False
            
            return self._check_mission_condition(mission, user_data, category)
            
        except Exception as e:
            self.logger.error(f"Error checking mission condition by category: {e}")
            return False
    
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
                return item.get('building_lv', 0) >= value
            elif category == 'unit':
                return item.get('total', 0) >= value
            elif category == 'research':
                return True  # 완료 여부만 체크
            
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
            
            # ItemManager를 통해 보상 지급
            item_manager = self._get_item_manager()
            item_manager.user_no = user_no
            
            for reward in rewards:
                item_idx = reward['item_idx']
                value = reward['value']
                
                # 아이템 추가
                item_manager.data = {"item_idx": item_idx, "quantity": value}
                await item_manager.add_item()
                
                self.logger.info(f"Granted item {item_idx}: {value} to user {user_no}")
            
            self.logger.info(f"Rewards granted: user={user_no}, mission_idx={mission_idx}")
            
        except Exception as e:
            self.logger.error(f"Error granting rewards: {e}")
    
    # ===== Manager 접근 헬퍼 =====
    
    def _get_building_manager(self):
        """BuildingManager 가져오기"""
        return self.redis_manager.get_building_manager()
    
    def _get_unit_manager(self):
        """UnitManager 가져오기"""
        return self.redis_manager.get_unit_manager()
    
    def _get_research_manager(self):
        """ResearchManager 가져오기"""
        return self.redis_manager.get_research_manager()
    
    def _get_item_manager(self):
        """ItemManager 가져오기"""
        return self.redis_manager.get_item_manager()