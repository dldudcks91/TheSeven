from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from datetime import datetime
import logging
from typing import Dict, Any, List, Optional


class AllianceManager:
    """
    연맹 관리자
    
    기능:
        - 연맹 생성/해산
        - 가입/탈퇴 (자유가입/신청-승인)
        - 멤버 관리 (추방, 직책 변경)
        - 공지사항 (맹주만 작성, 1개 유지)
        - 기부 (자원 → 연맹 경험치 + 연구 진행도 + 연맹코인 아이템)
        - 연맹 연구 (맹주/간부가 활성 연구 선택, 멤버 기부로 진행)
        - 연맹 버프 (BuffManager 연동)
    
    직책:
        1: 맹주
        2: 부맹주
        3: 간부
        4: 일반
    """
    
    CONFIG_TYPE_LEVEL = 'alliance_level'
    CONFIG_TYPE_POSITION = 'alliance_position'
    CONFIG_TYPE_RESEARCH = 'alliance_research'
    CONFIG_TYPE_DONATE = 'alliance_donate'
    
    # 직책 상수
    POSITION_LEADER = 1
    POSITION_VICE_LEADER = 2
    POSITION_OFFICER = 3
    POSITION_MEMBER = 4
    
    # 가입 방식
    JOIN_TYPE_FREE = "free"
    JOIN_TYPE_APPROVAL = "approval"
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    def user_no(self):
        return self._user_no

    @user_no.setter
    def user_no(self, no: int):
        if not isinstance(no, int):
            raise ValueError("user_no는 정수여야 합니다.")
        self._user_no = no

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("data는 딕셔너리여야 합니다.")
        self._data = value

    # ==================== 헬퍼 메서드 ====================
    
    def _get_level_config(self, level: int) -> Dict:
        """연맹 레벨 설정 조회"""
        configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE_LEVEL, {})
        return configs.get(level, {})
    
    def _get_position_config(self, position: int) -> Dict:
        """직책 설정 조회"""
        configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE_POSITION, {})
        return configs.get(position, {})
    
    def _get_research_config(self, research_idx: int, level: int) -> Dict:
        """연구 설정 조회 (연구별 레벨별)"""
        configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE_RESEARCH, {})
        research = configs.get(research_idx, {})
        return research.get(level, {})
    
    def _get_donate_config(self) -> Dict:
        """기부 설정 조회"""
        return GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE_DONATE, {})
    
    def _has_permission(self, position: int, permission: str) -> bool:
        """권한 확인"""
        config = self._get_position_config(position)
        return config.get(permission, False)
    
    async def _get_user_nation(self, user_no: int) -> Optional[Dict]:
        """유저 nation 정보 조회"""
        nation_redis = self.redis_manager.get_nation_manager()
        return await nation_redis.get_nation(user_no)
    
    async def _get_alliance_redis(self):
        """AllianceRedisManager 가져오기"""
        return self.redis_manager.get_alliance_manager()

    # ==================== 버프 관련 ====================
    
    async def _add_alliance_buff(self, user_no: int, alliance_id: int, level: int):
        """연맹 버프 추가"""
        try:
            level_config = self._get_level_config(level)
            buff_idx = level_config.get('buff_idx')
            buff_value = level_config.get('buff_value', 0)
            
            if buff_idx:
                buff_redis = self.redis_manager.get_buff_manager()
                buff_redis.user_no = user_no
                await buff_redis.add_permanent_buff(
                    user_no, "alliance", str(alliance_id), buff_idx, buff_value
                )
        except Exception as e:
            self.logger.error(f"Error adding alliance buff: {e}")
    
    async def _remove_alliance_buff(self, user_no: int, alliance_id: int):
        """연맹 버프 제거"""
        try:
            buff_redis = self.redis_manager.get_buff_manager()
            buff_redis.user_no = user_no
            await buff_redis.remove_permanent_buff(user_no, "alliance", str(alliance_id), "unit")
        except Exception as e:
            self.logger.error(f"Error removing alliance buff: {e}")
    
    async def _update_alliance_buff_for_all_members(self, alliance_id: int, level: int):
        """모든 멤버의 연맹 버프 업데이트"""
        try:
            alliance_redis = await self._get_alliance_redis()
            members = await alliance_redis.get_members(alliance_id)
            for user_no_str in members.keys():
                user_no = int(user_no_str)
                await self._remove_alliance_buff(user_no, alliance_id)
                await self._add_alliance_buff(user_no, alliance_id, level)
        except Exception as e:
            self.logger.error(f"Error updating buffs for all members: {e}")
    
    async def _check_level_up(self, alliance_id: int, current_exp: int, current_level: int) -> int:
        """레벨업 체크 및 처리"""
        new_level = current_level
        
        while True:
            next_level_config = self._get_level_config(new_level + 1)
            if not next_level_config:
                break
            required_exp = next_level_config.get('required_exp', float('inf'))
            if current_exp >= required_exp:
                new_level += 1
            else:
                break
        
        if new_level > current_level:
            await self._update_alliance_buff_for_all_members(alliance_id, new_level)
        
        return new_level

    # ==================== 연구 관련 헬퍼 ====================
    
    async def _check_research_level_up(self, alliance_id: int, research_idx: int, 
                                        current_exp: int, current_level: int) -> Dict:
        """연구 레벨업 체크"""
        new_level = current_level
        remaining_exp = current_exp
        
        while True:
            next_config = self._get_research_config(research_idx, new_level + 1)
            if not next_config:
                break
            required_exp = next_config.get('required_exp', float('inf'))
            if remaining_exp >= required_exp:
                remaining_exp -= required_exp
                new_level += 1
            else:
                break
        
        # 레벨업 발생 시 연구 버프 업데이트
        if new_level > current_level:
            await self._apply_research_buff(alliance_id, research_idx, new_level)
        
        return {"new_level": new_level, "remaining_exp": remaining_exp}
    
    async def _apply_research_buff(self, alliance_id: int, research_idx: int, level: int):
        """연구 버프 적용 (전 멤버)"""
        try:
            research_config = self._get_research_config(research_idx, level)
            buff_idx = research_config.get('buff_idx')
            buff_value = research_config.get('buff_value', 0)
            
            if not buff_idx:
                return
            
            alliance_redis = await self._get_alliance_redis()
            members = await alliance_redis.get_members(alliance_id)
            
            for user_no_str in members.keys():
                user_no = int(user_no_str)
                buff_redis = self.redis_manager.get_buff_manager()
                buff_redis.user_no = user_no
                await buff_redis.add_permanent_buff(
                    user_no, "alliance_research", str(research_idx), buff_idx, buff_value
                )
        except Exception as e:
            self.logger.error(f"Error applying research buff: {e}")

    # ==================== API: 연맹 정보 ====================
    
    async def alliance_info(self) -> Dict:
        """
        API 7001: 연맹 정보 조회
        
        Request data (optional):
            {"alliance_id": 1}  # 없으면 내 연맹
        """
        user_no = self.user_no
        
        try:
            alliance_redis = await self._get_alliance_redis()
            alliance_id = None
            
            if self._data and self._data.get('alliance_id'):
                alliance_id = self._data.get('alliance_id')
            else:
                nation = await self._get_user_nation(user_no)
                if nation:
                    alliance_id = nation.get('alliance_id')
            
            if not alliance_id:
                return {"success": True, "data": {"has_alliance": False, "alliance": None}}
            
            alliance_info = await alliance_redis.get_alliance_info(alliance_id)
            if not alliance_info:
                return {"success": False, "message": "연맹을 찾을 수 없습니다"}
            
            member_count = await alliance_redis.get_member_count(alliance_id)
            level_config = self._get_level_config(alliance_info.get('level', 1))
            
            # 내 직책
            my_position = None
            nation = await self._get_user_nation(user_no)
            if nation and nation.get('alliance_id') == alliance_id:
                my_position = nation.get('alliance_position')
            
            # 공지사항
            notice_data = await alliance_redis.get_notice(alliance_id)
            
            # 활성 연구
            active_research = await alliance_redis.get_active_research(alliance_id)
            
            return {
                "success": True,
                "data": {
                    "has_alliance": my_position is not None,
                    "my_position": my_position,
                    "alliance": {
                        **alliance_info,
                        "member_count": member_count,
                        "max_members": level_config.get('max_members', 20)
                    },
                    "notice": notice_data,
                    "active_research": active_research
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_info: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 연맹 생성 ====================
    
    async def alliance_create(self) -> Dict:
        """
        API 7002: 연맹 생성
        
        Request data:
            {"name": "연맹이름", "join_type": "free"}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            name = self._data.get('name', '').strip()
            join_type = self._data.get('join_type', self.JOIN_TYPE_FREE)
            
            if not name or len(name) < 2 or len(name) > 20:
                return {"success": False, "message": "연맹 이름은 2~20자여야 합니다"}
            
            nation = await self._get_user_nation(user_no)
            if nation and nation.get('alliance_id'):
                return {"success": False, "message": "이미 연맹에 가입되어 있습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            nation_redis = self.redis_manager.get_nation_manager()
            
            existing_id = await alliance_redis.get_alliance_id_by_name(name)
            if existing_id:
                return {"success": False, "message": "이미 사용 중인 연맹 이름입니다"}
            
            alliance_id = await alliance_redis.generate_alliance_id()
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                now = datetime.utcnow().isoformat()
                
                alliance_info = {
                    "alliance_id": alliance_id,
                    "name": name,
                    "level": 1,
                    "exp": 0,
                    "leader_no": user_no,
                    "join_type": join_type,
                    "created_at": now
                }
                
                member_data = {
                    "position": self.POSITION_LEADER,
                    "joined_at": now,
                    "donated_exp": 0,
                    "donated_coin": 0
                }
                
                # Redis 저장
                await alliance_redis.set_alliance_info(alliance_id, alliance_info)
                await alliance_redis.add_member(alliance_id, user_no, member_data)
                await alliance_redis.set_name_mapping(name, alliance_id)
                await alliance_redis.add_to_list(alliance_id)
                
                # Nation 업데이트
                await nation_redis.set_alliance_info(user_no, alliance_id, self.POSITION_LEADER)
                
                # DB 저장
                alliance_db = self.db_manager.get_alliance_manager()
                alliance_db.create_alliance(alliance_id, name, user_no, join_type)
                alliance_db.add_member(alliance_id, user_no, self.POSITION_LEADER, 0)
                alliance_db.commit()
                
                # 연맹 버프 추가
                await self._add_alliance_buff(user_no, alliance_id, 1)
                
                self.logger.info(f"Alliance created: id={alliance_id}, name={name}, leader={user_no}")
                
                return {
                    "success": True,
                    "data": {
                        "alliance_id": alliance_id,
                        "name": name
                    }
                }
                
            except Exception as e:
                alliance_db.rollback()
                raise e
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_create: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 연맹 가입 ====================
    
    async def alliance_join(self) -> Dict:
        """
        API 7003: 연맹 가입 (자유가입 또는 신청)
        
        Request data:
            {"alliance_id": 1}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            alliance_id = self._data.get('alliance_id')
            if not alliance_id:
                return {"success": False, "message": "Missing alliance_id"}
            
            nation = await self._get_user_nation(user_no)
            if nation and nation.get('alliance_id'):
                return {"success": False, "message": "이미 연맹에 가입되어 있습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            
            alliance_info = await alliance_redis.get_alliance_info(alliance_id)
            if not alliance_info:
                return {"success": False, "message": "연맹을 찾을 수 없습니다"}
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                member_count = await alliance_redis.get_member_count(alliance_id)
                level_config = self._get_level_config(alliance_info.get('level', 1))
                max_members = level_config.get('max_members', 20)
                
                if member_count >= max_members:
                    return {"success": False, "message": "연맹 인원이 가득 찼습니다"}
                
                join_type = alliance_info.get('join_type', self.JOIN_TYPE_FREE)
                now = datetime.utcnow().isoformat()
                
                if join_type == self.JOIN_TYPE_FREE:
                    member_data = {
                        "position": self.POSITION_MEMBER,
                        "joined_at": now,
                        "donated_exp": 0,
                        "donated_coin": 0
                    }
                    
                    await alliance_redis.add_member(alliance_id, user_no, member_data)
                    
                    nation_redis = self.redis_manager.get_nation_manager()
                    await nation_redis.set_alliance_info(user_no, alliance_id, self.POSITION_MEMBER)
                    
                    await self._add_alliance_buff(user_no, alliance_id, alliance_info.get('level', 1))
                    
                    return {"success": True, "data": {"status": "joined", "alliance_id": alliance_id}}
                else:
                    existing_app = await alliance_redis.get_application(alliance_id, user_no)
                    if existing_app:
                        return {"success": False, "message": "이미 가입 신청 중입니다"}
                    
                    app_data = {"applied_at": now}
                    await alliance_redis.add_application(alliance_id, user_no, app_data)
                    
                    return {"success": True, "data": {"status": "applied", "alliance_id": alliance_id}}
                    
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_join: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 연맹 탈퇴 ====================
    
    async def alliance_leave(self) -> Dict:
        """
        API 7004: 연맹 탈퇴
        """
        user_no = self.user_no
        
        try:
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            position = nation.get('alliance_position')
            
            if position == self.POSITION_LEADER:
                return {"success": False, "message": "맹주는 탈퇴할 수 없습니다. 연맹 해산 또는 맹주 위임을 해주세요"}
            
            alliance_redis = await self._get_alliance_redis()
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                await alliance_redis.remove_member(alliance_id, user_no)
                
                nation_redis = self.redis_manager.get_nation_manager()
                await nation_redis.clear_alliance_info(user_no)
                
                await self._remove_alliance_buff(user_no, alliance_id)
                
                return {"success": True, "data": {"left": True}}
                
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_leave: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 연맹 검색 ====================
    
    async def alliance_search(self) -> Dict:
        """
        API 7005: 연맹 검색
        
        Request data:
            {"keyword": "검색어"}
        """
        try:
            keyword = ""
            if self._data:
                keyword = self._data.get('keyword', '').strip()
            
            alliance_redis = await self._get_alliance_redis()
            
            if not keyword:
                results = await alliance_redis.search_alliances("", limit=20)
            else:
                results = await alliance_redis.search_alliances(keyword, limit=20)
            
            for r in results:
                level = r.get('level', 1)
                level_config = self._get_level_config(level)
                r['max_members'] = level_config.get('max_members', 20)
            
            return {"success": True, "data": {"alliances": results}}
            
        except Exception as e:
            self.logger.error(f"Error in alliance_search: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 멤버 목록 ====================
    
    async def alliance_members(self) -> Dict:
        """
        API 7006: 멤버 목록 조회
        
        Request data (optional):
            {"alliance_id": 1}
        """
        user_no = self.user_no
        
        try:
            alliance_id = None
            
            if self._data and self._data.get('alliance_id'):
                alliance_id = self._data.get('alliance_id')
            else:
                nation = await self._get_user_nation(user_no)
                if nation:
                    alliance_id = nation.get('alliance_id')
            
            if not alliance_id:
                return {"success": False, "message": "연맹을 찾을 수 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            members = await alliance_redis.get_members(alliance_id)
            
            member_list = []
            for user_no_str, member_data in members.items():
                position_config = self._get_position_config(member_data.get('position', 4))
                member_list.append({
                    "user_no": int(user_no_str),
                    "position": member_data.get('position'),
                    "position_name": position_config.get('name', '일반'),
                    "joined_at": member_data.get('joined_at'),
                    "donated_exp": member_data.get('donated_exp', 0),
                    "donated_coin": member_data.get('donated_coin', 0)
                })
            
            member_list.sort(key=lambda x: (x['position'], x['joined_at']))
            
            return {"success": True, "data": {"alliance_id": alliance_id, "members": member_list}}
            
        except Exception as e:
            self.logger.error(f"Error in alliance_members: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 멤버 추방 ====================
    
    async def alliance_kick(self) -> Dict:
        """
        API 7007: 멤버 추방
        
        Request data:
            {"target_user_no": 10002}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            target_user_no = self._data.get('target_user_no')
            if not target_user_no:
                return {"success": False, "message": "Missing target_user_no"}
            
            if target_user_no == user_no:
                return {"success": False, "message": "자기 자신을 추방할 수 없습니다"}
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if not self._has_permission(my_position, 'can_kick'):
                return {"success": False, "message": "추방 권한이 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            
            target_member = await alliance_redis.get_member(alliance_id, target_user_no)
            if not target_member:
                return {"success": False, "message": "해당 멤버를 찾을 수 없습니다"}
            
            target_position = target_member.get('position')
            if target_position <= my_position:
                return {"success": False, "message": "상위 직책의 멤버는 추방할 수 없습니다"}
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                await alliance_redis.remove_member(alliance_id, target_user_no)
                
                nation_redis = self.redis_manager.get_nation_manager()
                await nation_redis.clear_alliance_info(target_user_no)
                
                await self._remove_alliance_buff(target_user_no, alliance_id)
                
                return {"success": True, "data": {"kicked": True, "target_user_no": target_user_no}}
                
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_kick: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 직책 변경 ====================
    
    async def alliance_promote(self) -> Dict:
        """
        API 7008: 직책 변경
        
        Request data:
            {"target_user_no": 10002, "new_position": 3}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            target_user_no = self._data.get('target_user_no')
            new_position = self._data.get('new_position')
            
            if not target_user_no or not new_position:
                return {"success": False, "message": "Missing target_user_no or new_position"}
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if not self._has_permission(my_position, 'can_promote'):
                return {"success": False, "message": "직책 변경 권한이 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            nation_redis = self.redis_manager.get_nation_manager()
            
            target_member = await alliance_redis.get_member(alliance_id, target_user_no)
            if not target_member:
                return {"success": False, "message": "해당 멤버를 찾을 수 없습니다"}
            
            # 맹주 위임
            if new_position == self.POSITION_LEADER:
                if my_position != self.POSITION_LEADER:
                    return {"success": False, "message": "맹주만 맹주를 위임할 수 있습니다"}
                
                if not await alliance_redis.acquire_lock(alliance_id):
                    return {"success": False, "message": "잠시 후 다시 시도해주세요"}
                
                try:
                    # 기존 맹주 → 일반
                    my_member_data = await alliance_redis.get_member(alliance_id, user_no)
                    my_member_data['position'] = self.POSITION_MEMBER
                    await alliance_redis.update_member(alliance_id, user_no, my_member_data)
                    await nation_redis.set_alliance_info(user_no, alliance_id, self.POSITION_MEMBER)
                    
                    # 대상 → 맹주
                    target_member['position'] = self.POSITION_LEADER
                    await alliance_redis.update_member(alliance_id, target_user_no, target_member)
                    await nation_redis.set_alliance_info(target_user_no, alliance_id, self.POSITION_LEADER)
                    
                    # 연맹 정보 업데이트
                    alliance_info = await alliance_redis.get_alliance_info(alliance_id)
                    alliance_info['leader_no'] = target_user_no
                    await alliance_redis.set_alliance_info(alliance_id, alliance_info)
                    
                    return {"success": True, "data": {"promoted": True, "new_leader": target_user_no}}
                    
                finally:
                    await alliance_redis.release_lock(alliance_id)
            
            # 일반 직책 변경
            if new_position <= my_position:
                return {"success": False, "message": "자신보다 높은 직책을 부여할 수 없습니다"}
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                target_member['position'] = new_position
                await alliance_redis.update_member(alliance_id, target_user_no, target_member)
                await nation_redis.set_alliance_info(target_user_no, alliance_id, new_position)
                
                position_config = self._get_position_config(new_position)
                
                return {
                    "success": True,
                    "data": {
                        "promoted": True,
                        "target_user_no": target_user_no,
                        "new_position": new_position,
                        "position_name": position_config.get('name', '')
                    }
                }
                
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_promote: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 가입 신청 목록 ====================
    
    async def alliance_applications(self) -> Dict:
        """
        API 7009: 가입 신청 목록 조회
        """
        user_no = self.user_no
        
        try:
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if not self._has_permission(my_position, 'can_invite'):
                return {"success": False, "message": "신청 목록 조회 권한이 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            applications = await alliance_redis.get_applications(alliance_id)
            
            app_list = []
            for user_no_str, app_data in applications.items():
                app_list.append({
                    "user_no": int(user_no_str),
                    "applied_at": app_data.get('applied_at')
                })
            
            app_list.sort(key=lambda x: x['applied_at'])
            
            return {"success": True, "data": {"alliance_id": alliance_id, "applications": app_list}}
            
        except Exception as e:
            self.logger.error(f"Error in alliance_applications: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 가입 승인/거절 ====================
    
    async def alliance_approve(self) -> Dict:
        """
        API 7010: 가입 승인/거절
        
        Request data:
            {"target_user_no": 10003, "approve": true}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            target_user_no = self._data.get('target_user_no')
            approve = self._data.get('approve', False)
            
            if not target_user_no:
                return {"success": False, "message": "Missing target_user_no"}
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if not self._has_permission(my_position, 'can_invite'):
                return {"success": False, "message": "승인 권한이 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            
            application = await alliance_redis.get_application(alliance_id, target_user_no)
            if not application:
                return {"success": False, "message": "해당 가입 신청을 찾을 수 없습니다"}
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                await alliance_redis.remove_application(alliance_id, target_user_no)
                
                if approve:
                    member_count = await alliance_redis.get_member_count(alliance_id)
                    alliance_info = await alliance_redis.get_alliance_info(alliance_id)
                    level_config = self._get_level_config(alliance_info.get('level', 1))
                    max_members = level_config.get('max_members', 20)
                    
                    if member_count >= max_members:
                        return {"success": False, "message": "연맹 인원이 가득 찼습니다"}
                    
                    target_nation = await self._get_user_nation(target_user_no)
                    if target_nation and target_nation.get('alliance_id'):
                        return {"success": False, "message": "해당 유저가 이미 다른 연맹에 가입되어 있습니다"}
                    
                    now = datetime.utcnow().isoformat()
                    member_data = {
                        "position": self.POSITION_MEMBER,
                        "joined_at": now,
                        "donated_exp": 0,
                        "donated_coin": 0
                    }
                    
                    await alliance_redis.add_member(alliance_id, target_user_no, member_data)
                    
                    nation_redis = self.redis_manager.get_nation_manager()
                    await nation_redis.set_alliance_info(target_user_no, alliance_id, self.POSITION_MEMBER)
                    
                    await self._add_alliance_buff(target_user_no, alliance_id, alliance_info.get('level', 1))
                    
                    return {"success": True, "data": {"approved": True, "target_user_no": target_user_no}}
                else:
                    return {"success": True, "data": {"approved": False, "target_user_no": target_user_no}}
                    
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_approve: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 기부 ====================
    
    async def alliance_donate(self) -> Dict:
        """
        API 7011: 기부 (자원 → 연맹 경험치 + 활성 연구 진행도 + 연맹코인 아이템)
        
        Request data:
            {"resource_type": "food", "amount": 1000}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            resource_type = self._data.get('resource_type')
            amount = self._data.get('amount', 0)
            
            if not resource_type or amount <= 0:
                return {"success": False, "message": "자원 종류와 수량을 확인해주세요"}
            
            # 기부 설정 조회
            donate_config = self._get_donate_config()
            resource_config = donate_config.get(resource_type)
            if not resource_config:
                return {"success": False, "message": "기부할 수 없는 자원입니다"}
            
            exp_ratio = resource_config.get('exp_ratio', 100)       # 자원 N당 경험치 1
            coin_ratio = resource_config.get('coin_ratio', 100)     # 자원 N당 코인 1
            coin_item_idx = donate_config.get('coin_item_idx')      # 연맹코인 아이템 idx
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            
            # 자원 차감
            from services.resource.ResourceManager import ResourceManager
            resource_manager = ResourceManager(self.db_manager, self.redis_manager)
            resource_manager.user_no = user_no
            
            consume_result = await resource_manager.atomic_consume(
                user_no, resource_type, amount, f"alliance_donate:{alliance_id}"
            )
            
            if not consume_result.get('success'):
                return {"success": False, "message": "자원이 부족합니다"}
            
            # 계산
            exp_gained = amount // exp_ratio
            coin_gained = amount // coin_ratio
            
            alliance_redis = await self._get_alliance_redis()
            
            if not await alliance_redis.acquire_lock(alliance_id):
                await resource_manager.add_resource(user_no, resource_type, amount)
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                # 연맹 경험치 추가
                alliance_info = await alliance_redis.get_alliance_info(alliance_id)
                current_exp = alliance_info.get('exp', 0)
                current_level = alliance_info.get('level', 1)
                
                new_exp = current_exp + exp_gained
                alliance_info['exp'] = new_exp
                
                new_level = await self._check_level_up(alliance_id, new_exp, current_level)
                alliance_info['level'] = new_level
                
                await alliance_redis.set_alliance_info(alliance_id, alliance_info)
                
                # 활성 연구 진행도 추가
                research_leveled_up = False
                active_research = await alliance_redis.get_active_research(alliance_id)
                
                if active_research:
                    research_idx = active_research.get('research_idx')
                    research_data = await alliance_redis.get_research(alliance_id, research_idx)
                    
                    if not research_data:
                        research_data = {"level": 0, "current_exp": 0}
                    
                    research_data['current_exp'] = research_data.get('current_exp', 0) + exp_gained
                    
                    # 연구 레벨업 체크
                    result = await self._check_research_level_up(
                        alliance_id, research_idx,
                        research_data['current_exp'], research_data.get('level', 0)
                    )
                    
                    if result['new_level'] > research_data.get('level', 0):
                        research_leveled_up = True
                        research_data['completed_at'] = datetime.utcnow().isoformat()
                    
                    research_data['level'] = result['new_level']
                    research_data['current_exp'] = result['remaining_exp']
                    
                    await alliance_redis.set_research(alliance_id, research_idx, research_data)
                
                # 멤버 기부 기록 업데이트
                member_data = await alliance_redis.get_member(alliance_id, user_no)
                member_data['donated_exp'] = member_data.get('donated_exp', 0) + exp_gained
                member_data['donated_coin'] = member_data.get('donated_coin', 0) + coin_gained
                await alliance_redis.update_member(alliance_id, user_no, member_data)
                
                # 연맹코인 아이템 지급
                if coin_item_idx and coin_gained > 0:
                    from services.item.ItemManager import ItemManager
                    item_manager = ItemManager(self.db_manager, self.redis_manager)
                    item_manager.user_no = user_no
                    await item_manager.add_item(user_no, coin_item_idx, coin_gained)
                
                return {
                    "success": True,
                    "data": {
                        "resource_type": resource_type,
                        "donated_amount": amount,
                        "exp_gained": exp_gained,
                        "coin_gained": coin_gained,
                        "alliance_exp": new_exp,
                        "alliance_level": new_level,
                        "leveled_up": new_level > current_level,
                        "research_leveled_up": research_leveled_up
                    }
                }
                
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_donate: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 가입 방식 변경 ====================
    
    async def alliance_join_type(self) -> Dict:
        """
        API 7012: 가입 방식 변경
        
        Request data:
            {"join_type": "approval"}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            new_join_type = self._data.get('join_type')
            if new_join_type not in [self.JOIN_TYPE_FREE, self.JOIN_TYPE_APPROVAL]:
                return {"success": False, "message": "Invalid join_type"}
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if not self._has_permission(my_position, 'can_set_join_type'):
                return {"success": False, "message": "가입 방식 변경 권한이 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            alliance_info = await alliance_redis.get_alliance_info(alliance_id)
            alliance_info['join_type'] = new_join_type
            await alliance_redis.set_alliance_info(alliance_id, alliance_info)
            
            return {"success": True, "data": {"join_type": new_join_type}}
            
        except Exception as e:
            self.logger.error(f"Error in alliance_join_type: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 연맹 해산 ====================
    
    async def alliance_disband(self) -> Dict:
        """
        API 7013: 연맹 해산
        """
        user_no = self.user_no
        
        try:
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if not self._has_permission(my_position, 'can_disband'):
                return {"success": False, "message": "연맹 해산 권한이 없습니다"}
            
            alliance_redis = await self._get_alliance_redis()
            
            if not await alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                alliance_info = await alliance_redis.get_alliance_info(alliance_id)
                alliance_name = alliance_info.get('name', '')
                
                # 모든 멤버 연맹 정보 및 버프 제거
                nation_redis = self.redis_manager.get_nation_manager()
                members = await alliance_redis.get_members(alliance_id)
                
                for member_user_no_str in members.keys():
                    member_user_no = int(member_user_no_str)
                    await nation_redis.clear_alliance_info(member_user_no)
                    await self._remove_alliance_buff(member_user_no, alliance_id)
                
                # Redis 전체 삭제
                await alliance_redis.delete_all_alliance_data(alliance_id, alliance_name)
                
                # DB 삭제
                alliance_db = self.db_manager.get_alliance_manager()
                alliance_db.delete_all_members(alliance_id)
                alliance_db.delete_all_applications(alliance_id)
                alliance_db.delete_alliance(alliance_id)
                alliance_db.commit()
                
                return {"success": True, "data": {"disbanded": True}}
            
            except Exception as e:
                alliance_db.rollback()
                raise e
            finally:
                await alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_disband: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 공지사항 조회 ====================
    
    async def alliance_notice(self) -> Dict:
        """
        API 7014: 공지사항 조회
        """
        user_no = self.user_no
        
        try:
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            alliance_redis = await self._get_alliance_redis()
            
            notice_data = await alliance_redis.get_notice(alliance_id)
            
            return {
                "success": True,
                "data": {
                    "notice": notice_data
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_notice: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 공지사항 작성 ====================
    
    async def alliance_notice_write(self) -> Dict:
        """
        API 7015: 공지사항 작성 (맹주만)
        
        Request data:
            {"content": "공지 내용"}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            content = self._data.get('content', '').strip()
            if not content:
                return {"success": False, "message": "공지 내용을 입력해주세요"}
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            if my_position != self.POSITION_LEADER:
                return {"success": False, "message": "맹주만 공지를 작성할 수 있습니다"}
            
            now = datetime.utcnow().isoformat()
            
            notice_data = {
                "content": content,
                "writer_no": user_no,
                "updated_at": now
            }
            
            alliance_redis = await self._get_alliance_redis()
            await alliance_redis.set_notice(alliance_id, notice_data)
            
            # DB 업데이트
            alliance_info = await alliance_redis.get_alliance_info(alliance_id)
            alliance_info['notice'] = content
            alliance_info['notice_updated_at'] = now
            await alliance_redis.set_alliance_info(alliance_id, alliance_info)
            
            return {
                "success": True,
                "data": {
                    "notice": notice_data
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_notice_write: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 연구 목록 ====================
    
    async def alliance_research_list(self) -> Dict:
        """
        API 7016: 연구 목록 조회
        """
        user_no = self.user_no
        
        try:
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            alliance_redis = await self._get_alliance_redis()
            
            # 전체 연구 상태
            all_research = await alliance_redis.get_all_research(alliance_id)
            
            # 활성 연구
            active_research = await alliance_redis.get_active_research(alliance_id)
            
            # meta_data에서 연구 목록 가져와서 진행 상태 매핑
            research_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE_RESEARCH, {})
            
            research_list = []
            for research_idx, level_configs in research_configs.items():
                research_data = all_research.get(str(research_idx), {})
                current_level = research_data.get('level', 0) if research_data else 0
                current_exp = research_data.get('current_exp', 0) if research_data else 0
                
                # 다음 레벨 설정
                next_config = self._get_research_config(research_idx, current_level + 1)
                required_exp = next_config.get('required_exp', 0) if next_config else 0
                max_level = max(level_configs.keys()) if level_configs else 0
                
                is_active = (active_research and 
                           active_research.get('research_idx') == research_idx)
                
                research_list.append({
                    "research_idx": research_idx,
                    "level": current_level,
                    "max_level": max_level,
                    "current_exp": current_exp,
                    "required_exp": required_exp,
                    "is_max": current_level >= max_level,
                    "is_active": is_active
                })
            
            return {
                "success": True,
                "data": {
                    "research_list": research_list,
                    "active_research": active_research
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_research_list: {e}")
            return {"success": False, "message": str(e)}

    # ==================== API: 활성 연구 선택 ====================
    
    async def alliance_research_select(self) -> Dict:
        """
        API 7017: 활성 연구 선택 (맹주/간부)
        
        Request data:
            {"research_idx": 1}
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            research_idx = self._data.get('research_idx')
            if not research_idx:
                return {"success": False, "message": "Missing research_idx"}
            
            nation = await self._get_user_nation(user_no)
            if not nation or not nation.get('alliance_id'):
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = nation.get('alliance_id')
            my_position = nation.get('alliance_position')
            
            # 맹주/간부만 가능
            if my_position > self.POSITION_OFFICER:
                return {"success": False, "message": "연구 선택 권한이 없습니다"}
            
            # 연구 존재 여부 확인
            research_configs = GameDataManager.REQUIRE_CONFIGS.get(self.CONFIG_TYPE_RESEARCH, {})
            if research_idx not in research_configs:
                return {"success": False, "message": "존재하지 않는 연구입니다"}
            
            # 이미 만렙인지 확인
            alliance_redis = await self._get_alliance_redis()
            research_data = await alliance_redis.get_research(alliance_id, research_idx)
            current_level = research_data.get('level', 0) if research_data else 0
            max_level = max(research_configs[research_idx].keys()) if research_configs[research_idx] else 0
            
            if current_level >= max_level:
                return {"success": False, "message": "이미 최대 레벨에 도달한 연구입니다"}
            
            now = datetime.utcnow().isoformat()
            
            active_data = {
                "research_idx": research_idx,
                "activated_at": now,
                "activated_by": user_no
            }
            
            await alliance_redis.set_active_research(alliance_id, active_data)
            
            return {
                "success": True,
                "data": {
                    "active_research": active_data
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_research_select: {e}")
            return {"success": False, "message": str(e)}