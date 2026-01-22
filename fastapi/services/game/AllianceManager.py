from services.system.GameDataManager import GameDataManager
from services.redis_manager import RedisManager
from services.db_manager import DBManager
from sqlalchemy.orm import Session
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
        - 기부 (경험치 획득)
        - 연맹 버프 (BuffManager 연동)
    
    직책:
        1: 맹주
        2: 부맹주
        3: 간부
        4: 일반
    """
    
    CONFIG_TYPE_LEVEL = 'alliance_level'
    CONFIG_TYPE_POSITION = 'alliance_position'
    
    # 직책 상수
    POSITION_LEADER = 1
    POSITION_VICE_LEADER = 2
    POSITION_OFFICER = 3
    POSITION_MEMBER = 4
    
    # 가입 방식
    JOIN_TYPE_FREE = "free"
    JOIN_TYPE_APPROVAL = "approval"
    
    # 기부 비율 (식량 100 → 경험치 1)
    DONATE_RATIO = 100
    
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self._user_no: int = None
        self._data: dict = None
        self.db = db_session
        self.redis_manager = redis_manager
        self.db_manager = db_manager
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
    
    def _has_permission(self, position: int, permission: str) -> bool:
        """권한 확인"""
        config = self._get_position_config(position)
        return config.get(permission, False)
    
    async def _get_user_alliance_info(self, user_no: int) -> Optional[Dict]:
        """유저의 연맹 정보 조회 (Redis)"""
        return await self.alliance_redis.get_user_alliance(user_no)
    
    async def _add_alliance_buff(self, user_no: int, alliance_id: int, level: int):
        """연맹 버프 추가 (BuffManager 연동)"""
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
                self.logger.info(f"Alliance buff added: user={user_no}, buff_idx={buff_idx}, value={buff_value}")
        except Exception as e:
            self.logger.error(f"Error adding alliance buff: {e}")
    
    async def _remove_alliance_buff(self, user_no: int, alliance_id: int):
        """연맹 버프 제거"""
        try:
            
            buff_redis = self.redis_manager.get_buff_manager()
            buff_redis.user_no = user_no
            
            await buff_redis.remove_permanent_buff(user_no, "alliance", str(alliance_id), "unit")
            self.logger.info(f"Alliance buff removed: user={user_no}, alliance={alliance_id}")
        except Exception as e:
            self.logger.error(f"Error removing alliance buff: {e}")
    
    async def _update_alliance_buff_for_all_members(self, alliance_id: int, level: int):
        """모든 멤버의 연맹 버프 업데이트"""
        try:
            members = await self.alliance_redis.get_alliance_members(alliance_id)
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
                self.logger.info(f"Alliance {alliance_id} leveled up to {new_level}")
            else:
                break
        
        # 레벨업 발생 시 버프 업데이트
        if new_level > current_level:
            await self._update_alliance_buff_for_all_members(alliance_id, new_level)
        
        return new_level

    # ==================== API 메서드 ====================
    
    async def alliance_info(self) -> Dict:
        """
        API 7001: 연맹 정보 조회
        
        - 내 연맹 정보 또는 특정 연맹 정보 조회
        
        Request data (optional):
            {"alliance_id": 1}  # 없으면 내 연맹
        """
        user_no = self.user_no
        
        try:
            alliance_id = None
            
            # 특정 연맹 조회
            if self._data and self._data.get('alliance_id'):
                alliance_id = self._data.get('alliance_id')
            else:
                # 내 연맹 조회
                user_alliance = await self._get_user_alliance_info(user_no)
                if user_alliance:
                    alliance_id = user_alliance.get('alliance_id')
            
            if not alliance_id:
                return {
                    "success": True,
                    "data": {
                        "has_alliance": False,
                        "alliance": None
                    }
                }
            
            # 연맹 정보 조회 (Redis)
            alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
            if not alliance_info:
                return {"success": False, "message": "Alliance not found"}
            
            # 멤버 수 조회
            member_count = await self.alliance_redis.get_member_count(alliance_id)
            level_config = self._get_level_config(alliance_info.get('level', 1))
            
            # 내 직책 (내 연맹인 경우)
            my_position = None
            user_alliance = await self._get_user_alliance_info(user_no)
            if user_alliance and user_alliance.get('alliance_id') == alliance_id:
                my_position = user_alliance.get('position')
            
            return {
                "success": True,
                "data": {
                    "has_alliance": my_position is not None,
                    "my_position": my_position,
                    "alliance": {
                        **alliance_info,
                        "member_count": member_count,
                        "max_members": level_config.get('max_members', 20)
                    }
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_info: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_create(self) -> Dict:
        """
        API 7002: 연맹 생성
        
        Request data:
            {"name": "연맹이름", "join_type": "free"}  # free 또는 approval
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            name = self._data.get('name', '').strip()
            join_type = self._data.get('join_type', self.JOIN_TYPE_FREE)
            
            # 이름 유효성 검사
            if not name or len(name) < 2 or len(name) > 20:
                return {"success": False, "message": "연맹 이름은 2~20자여야 합니다"}
            
            # 이미 연맹 가입 여부 확인
            user_alliance = await self._get_user_alliance_info(user_no)
            if user_alliance:
                return {"success": False, "message": "이미 연맹에 가입되어 있습니다"}
            
            # 이름 중복 확인
            existing_id = await self.alliance_redis.get_alliance_id_by_name(name)
            if existing_id:
                return {"success": False, "message": "이미 사용 중인 연맹 이름입니다"}
            
            # 연맹 ID 생성
            alliance_id = await self.alliance_redis.generate_alliance_id()
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                now = datetime.utcnow().isoformat()
                
                # 연맹 정보 생성
                alliance_info = {
                    "alliance_id": alliance_id,
                    "name": name,
                    "level": 1,
                    "exp": 0,
                    "leader_no": user_no,
                    "join_type": join_type,
                    "created_at": now
                }
                
                # 멤버 정보 (맹주)
                member_data = {
                    "position": self.POSITION_LEADER,
                    "joined_at": now,
                    "donated_exp": 0
                }
                
                # 유저 연맹 정보
                user_alliance_data = {
                    "alliance_id": alliance_id,
                    "position": self.POSITION_LEADER
                }
                
                # Redis 저장
                await self.alliance_redis.set_alliance_info(alliance_id, alliance_info)
                await self.alliance_redis.add_member(alliance_id, user_no, member_data)
                await self.alliance_redis.set_user_alliance(user_no, user_alliance_data)
                await self.alliance_redis.set_alliance_name_mapping(name, alliance_id)
                await self.alliance_redis.add_to_alliance_list(alliance_id)
                
                # DB 저장 (동기)
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
                self.db.rollback()
                raise e
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_create: {e}")
            return {"success": False, "message": str(e)}

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
            
            # 이미 연맹 가입 여부 확인
            user_alliance = await self._get_user_alliance_info(user_no)
            if user_alliance:
                return {"success": False, "message": "이미 연맹에 가입되어 있습니다"}
            
            # 연맹 정보 확인
            alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
            if not alliance_info:
                return {"success": False, "message": "연맹을 찾을 수 없습니다"}
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                # 인원 확인
                member_count = await self.alliance_redis.get_member_count(alliance_id)
                level_config = self._get_level_config(alliance_info.get('level', 1))
                max_members = level_config.get('max_members', 20)
                
                if member_count >= max_members:
                    return {"success": False, "message": "연맹 인원이 가득 찼습니다"}
                
                join_type = alliance_info.get('join_type', self.JOIN_TYPE_FREE)
                now = datetime.utcnow().isoformat()
                
                if join_type == self.JOIN_TYPE_FREE:
                    # 자유가입: 즉시 가입
                    member_data = {
                        "position": self.POSITION_MEMBER,
                        "joined_at": now,
                        "donated_exp": 0
                    }
                    
                    user_alliance_data = {
                        "alliance_id": alliance_id,
                        "position": self.POSITION_MEMBER
                    }
                    
                    # Redis 저장
                    await self.alliance_redis.add_member(alliance_id, user_no, member_data)
                    await self.alliance_redis.set_user_alliance(user_no, user_alliance_data)
                    
                    # 연맹 버프 추가
                    await self._add_alliance_buff(user_no, alliance_id, alliance_info.get('level', 1))
                    
                    self.logger.info(f"User {user_no} joined alliance {alliance_id}")
                    
                    return {
                        "success": True,
                        "data": {
                            "status": "joined",
                            "alliance_id": alliance_id
                        }
                    }
                    
                else:
                    # 승인제: 가입 신청
                    existing_app = await self.alliance_redis.get_application(alliance_id, user_no)
                    if existing_app:
                        return {"success": False, "message": "이미 가입 신청 중입니다"}
                    
                    app_data = {"applied_at": now}
                    await self.alliance_redis.add_application(alliance_id, user_no, app_data)
                    
                    self.logger.info(f"User {user_no} applied to alliance {alliance_id}")
                    
                    return {
                        "success": True,
                        "data": {
                            "status": "applied",
                            "alliance_id": alliance_id
                        }
                    }
                    
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_join: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_leave(self) -> Dict:
        """
        API 7004: 연맹 탈퇴
        
        - 맹주는 탈퇴 불가 (해산 또는 위임 필요)
        """
        user_no = self.user_no
        
        try:
            # 내 연맹 정보 확인
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            position = user_alliance.get('position')
            
            # 맹주 탈퇴 불가
            if position == self.POSITION_LEADER:
                return {"success": False, "message": "맹주는 탈퇴할 수 없습니다. 연맹 해산 또는 맹주 위임을 해주세요"}
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                # Redis에서 제거
                await self.alliance_redis.remove_member(alliance_id, user_no)
                await self.alliance_redis.delete_user_alliance(user_no)
                
                # 연맹 버프 제거
                await self._remove_alliance_buff(user_no, alliance_id)
                
                self.logger.info(f"User {user_no} left alliance {alliance_id}")
                
                return {"success": True, "data": {"left": True}}
                
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_leave: {e}")
            return {"success": False, "message": str(e)}

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
            
            if not keyword:
                # 키워드 없으면 전체 목록 (상위 20개)
                results = await self.alliance_redis.search_alliances("", limit=20)
            else:
                results = await self.alliance_redis.search_alliances(keyword, limit=20)
            
            # 레벨별 max_members 추가
            for r in results:
                level = r.get('level', 1)
                level_config = self._get_level_config(level)
                r['max_members'] = level_config.get('max_members', 20)
            
            return {
                "success": True,
                "data": {
                    "alliances": results
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_search: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_members(self) -> Dict:
        """
        API 7006: 멤버 목록 조회
        
        Request data (optional):
            {"alliance_id": 1}  # 없으면 내 연맹
        """
        user_no = self.user_no
        
        try:
            alliance_id = None
            
            if self._data and self._data.get('alliance_id'):
                alliance_id = self._data.get('alliance_id')
            else:
                user_alliance = await self._get_user_alliance_info(user_no)
                if user_alliance:
                    alliance_id = user_alliance.get('alliance_id')
            
            if not alliance_id:
                return {"success": False, "message": "연맹을 찾을 수 없습니다"}
            
            members = await self.alliance_redis.get_alliance_members(alliance_id)
            
            # 멤버 정보 정리
            member_list = []
            for user_no_str, member_data in members.items():
                position_config = self._get_position_config(member_data.get('position', 4))
                member_list.append({
                    "user_no": int(user_no_str),
                    "position": member_data.get('position'),
                    "position_name": position_config.get('name', '일반'),
                    "joined_at": member_data.get('joined_at'),
                    "donated_exp": member_data.get('donated_exp', 0)
                })
            
            # 직책순 정렬
            member_list.sort(key=lambda x: (x['position'], x['joined_at']))
            
            return {
                "success": True,
                "data": {
                    "alliance_id": alliance_id,
                    "members": member_list
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_members: {e}")
            return {"success": False, "message": str(e)}

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
            
            # 자기 자신 추방 불가
            if target_user_no == user_no:
                return {"success": False, "message": "자기 자신을 추방할 수 없습니다"}
            
            # 내 연맹 정보 확인
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            my_position = user_alliance.get('position')
            
            # 추방 권한 확인
            if not self._has_permission(my_position, 'can_kick'):
                return {"success": False, "message": "추방 권한이 없습니다"}
            
            # 대상 확인
            target_member = await self.alliance_redis.get_member(alliance_id, target_user_no)
            if not target_member:
                return {"success": False, "message": "해당 멤버를 찾을 수 없습니다"}
            
            target_position = target_member.get('position')
            
            # 상위 직책 추방 불가
            if target_position <= my_position:
                return {"success": False, "message": "상위 직책의 멤버는 추방할 수 없습니다"}
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                # Redis에서 제거
                await self.alliance_redis.remove_member(alliance_id, target_user_no)
                await self.alliance_redis.delete_user_alliance(target_user_no)
                
                # 연맹 버프 제거
                await self._remove_alliance_buff(target_user_no, alliance_id)
                
                self.logger.info(f"User {target_user_no} kicked from alliance {alliance_id} by {user_no}")
                
                return {"success": True, "data": {"kicked": True, "target_user_no": target_user_no}}
                
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_kick: {e}")
            return {"success": False, "message": str(e)}

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
            
            # 내 연맹 정보 확인
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            my_position = user_alliance.get('position')
            
            # 직책 변경 권한 확인
            if not self._has_permission(my_position, 'can_promote'):
                return {"success": False, "message": "직책 변경 권한이 없습니다"}
            
            # 대상 확인
            target_member = await self.alliance_redis.get_member(alliance_id, target_user_no)
            if not target_member:
                return {"success": False, "message": "해당 멤버를 찾을 수 없습니다"}
            
            # 맹주 위임 처리
            if new_position == self.POSITION_LEADER:
                if my_position != self.POSITION_LEADER:
                    return {"success": False, "message": "맹주만 맹주를 위임할 수 있습니다"}
                
                # 락 획득
                if not await self.alliance_redis.acquire_lock(alliance_id):
                    return {"success": False, "message": "잠시 후 다시 시도해주세요"}
                
                try:
                    # 기존 맹주 → 일반 (Redis)
                    my_member_data = await self.alliance_redis.get_member(alliance_id, user_no)
                    my_member_data['position'] = self.POSITION_MEMBER
                    await self.alliance_redis.update_member(alliance_id, user_no, my_member_data)
                    await self.alliance_redis.set_user_alliance(user_no, {
                        "alliance_id": alliance_id,
                        "position": self.POSITION_MEMBER
                    })
                    
                    # 대상 → 맹주 (Redis)
                    target_member['position'] = self.POSITION_LEADER
                    await self.alliance_redis.update_member(alliance_id, target_user_no, target_member)
                    await self.alliance_redis.set_user_alliance(target_user_no, {
                        "alliance_id": alliance_id,
                        "position": self.POSITION_LEADER
                    })
                    
                    # 연맹 정보 업데이트 (Redis)
                    alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
                    alliance_info['leader_no'] = target_user_no
                    await self.alliance_redis.set_alliance_info(alliance_id, alliance_info)
                    
                    self.logger.info(f"Leader transferred: {user_no} -> {target_user_no} in alliance {alliance_id}")
                    
                    return {"success": True, "data": {"promoted": True, "new_leader": target_user_no}}
                    
                finally:
                    await self.alliance_redis.release_lock(alliance_id)
            
            # 일반 직책 변경
            if new_position <= my_position:
                return {"success": False, "message": "자신보다 높은 직책을 부여할 수 없습니다"}
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                target_member['position'] = new_position
                await self.alliance_redis.update_member(alliance_id, target_user_no, target_member)
                await self.alliance_redis.set_user_alliance(target_user_no, {
                    "alliance_id": alliance_id,
                    "position": new_position
                })
                
                position_config = self._get_position_config(new_position)
                
                self.logger.info(f"User {target_user_no} promoted to {new_position} in alliance {alliance_id}")
                
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
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_promote: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_applications(self) -> Dict:
        """
        API 7009: 가입 신청 목록 조회
        """
        user_no = self.user_no
        
        try:
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            my_position = user_alliance.get('position')
            
            # 초대 권한 확인 (신청 목록 조회 권한과 동일)
            if not self._has_permission(my_position, 'can_invite'):
                return {"success": False, "message": "신청 목록 조회 권한이 없습니다"}
            
            applications = await self.alliance_redis.get_applications(alliance_id)
            
            app_list = []
            for user_no_str, app_data in applications.items():
                app_list.append({
                    "user_no": int(user_no_str),
                    "applied_at": app_data.get('applied_at')
                })
            
            # 신청일 순 정렬
            app_list.sort(key=lambda x: x['applied_at'])
            
            return {
                "success": True,
                "data": {
                    "alliance_id": alliance_id,
                    "applications": app_list
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_applications: {e}")
            return {"success": False, "message": str(e)}

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
            
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            my_position = user_alliance.get('position')
            
            if not self._has_permission(my_position, 'can_invite'):
                return {"success": False, "message": "승인 권한이 없습니다"}
            
            # 신청 확인
            application = await self.alliance_redis.get_application(alliance_id, target_user_no)
            if not application:
                return {"success": False, "message": "해당 가입 신청을 찾을 수 없습니다"}
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                # 신청 제거
                await self.alliance_redis.remove_application(alliance_id, target_user_no)
                
                if approve:
                    # 인원 확인
                    member_count = await self.alliance_redis.get_member_count(alliance_id)
                    alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
                    level_config = self._get_level_config(alliance_info.get('level', 1))
                    max_members = level_config.get('max_members', 20)
                    
                    if member_count >= max_members:
                        return {"success": False, "message": "연맹 인원이 가득 찼습니다"}
                    
                    # 대상이 이미 다른 연맹 가입 여부 확인
                    target_alliance = await self._get_user_alliance_info(target_user_no)
                    if target_alliance:
                        return {"success": False, "message": "해당 유저가 이미 다른 연맹에 가입되어 있습니다"}
                    
                    now = datetime.utcnow().isoformat()
                    member_data = {
                        "position": self.POSITION_MEMBER,
                        "joined_at": now,
                        "donated_exp": 0
                    }
                    
                    # Redis 저장
                    await self.alliance_redis.add_member(alliance_id, target_user_no, member_data)
                    await self.alliance_redis.set_user_alliance(target_user_no, {
                        "alliance_id": alliance_id,
                        "position": self.POSITION_MEMBER
                    })
                    
                    # 연맹 버프 추가
                    await self._add_alliance_buff(target_user_no, alliance_id, alliance_info.get('level', 1))
                    
                    self.logger.info(f"User {target_user_no} approved to alliance {alliance_id}")
                    
                    return {"success": True, "data": {"approved": True, "target_user_no": target_user_no}}
                else:
                    self.logger.info(f"User {target_user_no} rejected from alliance {alliance_id}")
                    return {"success": True, "data": {"approved": False, "target_user_no": target_user_no}}
                    
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_approve: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_donate(self) -> Dict:
        """
        API 7011: 기부 (식량 → 경험치)
        
        Request data:
            {"amount": 1000}  # 식량 수량
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            amount = self._data.get('amount', 0)
            if amount <= 0:
                return {"success": False, "message": "기부 수량은 0보다 커야 합니다"}
            
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            
            # 식량 확인 및 차감 (ResourceManager 사용)
            from services.resource.ResourceManager import ResourceManager
            resource_manager = ResourceManager(self.db, self.redis_manager)
            resource_manager.user_no = user_no
            
            # 식량 차감 시도
            consume_result = await resource_manager.atomic_consume(
                user_no, 'food', amount, f"alliance_donate:{alliance_id}"
            )
            
            if not consume_result.get('success'):
                return {"success": False, "message": "식량이 부족합니다"}
            
            # 경험치 계산
            exp_gained = amount // self.DONATE_RATIO
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                # 롤백: 식량 복구
                await resource_manager.add_resource(user_no, 'food', amount)
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                # 연맹 경험치 추가 (Redis)
                alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
                current_exp = alliance_info.get('exp', 0)
                current_level = alliance_info.get('level', 1)
                
                new_exp = current_exp + exp_gained
                alliance_info['exp'] = new_exp
                
                # 레벨업 체크
                new_level = await self._check_level_up(alliance_id, new_exp, current_level)
                alliance_info['level'] = new_level
                
                await self.alliance_redis.set_alliance_info(alliance_id, alliance_info)
                
                # 멤버 기부 기록 업데이트 (Redis)
                member_data = await self.alliance_redis.get_member(alliance_id, user_no)
                member_data['donated_exp'] = member_data.get('donated_exp', 0) + exp_gained
                await self.alliance_redis.update_member(alliance_id, user_no, member_data)
                
                self.logger.info(f"User {user_no} donated {amount} food ({exp_gained} exp) to alliance {alliance_id}")
                
                return {
                    "success": True,
                    "data": {
                        "donated_food": amount,
                        "exp_gained": exp_gained,
                        "alliance_exp": new_exp,
                        "alliance_level": new_level,
                        "leveled_up": new_level > current_level
                    }
                }
                
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_donate: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_set_join_type(self) -> Dict:
        """
        API 7012: 가입 방식 변경
        
        Request data:
            {"join_type": "approval"}  # free 또는 approval
        """
        user_no = self.user_no
        
        try:
            if not self._data:
                return {"success": False, "message": "Missing data"}
            
            new_join_type = self._data.get('join_type')
            if new_join_type not in [self.JOIN_TYPE_FREE, self.JOIN_TYPE_APPROVAL]:
                return {"success": False, "message": "Invalid join_type"}
            
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            my_position = user_alliance.get('position')
            
            if not self._has_permission(my_position, 'can_set_join_type'):
                return {"success": False, "message": "가입 방식 변경 권한이 없습니다"}
            
            # Redis 업데이트
            alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
            alliance_info['join_type'] = new_join_type
            await self.alliance_redis.set_alliance_info(alliance_id, alliance_info)
            
            self.logger.info(f"Alliance {alliance_id} join_type changed to {new_join_type}")
            
            return {
                "success": True,
                "data": {
                    "join_type": new_join_type
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in alliance_set_join_type: {e}")
            return {"success": False, "message": str(e)}

    async def alliance_disband(self) -> Dict:
        """
        API 7013: 연맹 해산
        
        - 맹주만 가능
        - 모든 멤버의 연맹 정보 및 버프 제거
        """
        user_no = self.user_no
        
        try:
            user_alliance = await self._get_user_alliance_info(user_no)
            if not user_alliance:
                return {"success": False, "message": "연맹에 가입되어 있지 않습니다"}
            
            alliance_id = user_alliance.get('alliance_id')
            my_position = user_alliance.get('position')
            
            if not self._has_permission(my_position, 'can_disband'):
                return {"success": False, "message": "연맹 해산 권한이 없습니다"}
            
            # 락 획득
            if not await self.alliance_redis.acquire_lock(alliance_id):
                return {"success": False, "message": "잠시 후 다시 시도해주세요"}
            
            try:
                alliance_info = await self.alliance_redis.get_alliance_info(alliance_id)
                alliance_name = alliance_info.get('name', '')
                
                # 모든 멤버의 연맹 정보 및 버프 제거
                members = await self.alliance_redis.get_alliance_members(alliance_id)
                for member_user_no_str in members.keys():
                    member_user_no = int(member_user_no_str)
                    await self.alliance_redis.delete_user_alliance(member_user_no)
                    await self._remove_alliance_buff(member_user_no, alliance_id)
                
                # Redis 데이터 삭제
                await self.alliance_redis.delete_all_members(alliance_id)
                await self.alliance_redis.delete_all_applications(alliance_id)
                await self.alliance_redis.delete_alliance_info(alliance_id)
                await self.alliance_redis.delete_alliance_name_mapping(alliance_name)
                await self.alliance_redis.remove_from_alliance_list(alliance_id)
                
                # DB 데이터 삭제 (동기)
                self.alliance_db.delete_all_members(alliance_id)
                self.alliance_db.delete_all_applications(alliance_id)
                self.alliance_db.delete_alliance(alliance_id)
                self.db.commit()
                
                self.logger.info(f"Alliance {alliance_id} ({alliance_name}) disbanded by {user_no}")
                
                return {"success": True, "data": {"disbanded": True}}
            
            except Exception as e:
                self.db.rollback()
                raise e
            finally:
                await self.alliance_redis.release_lock(alliance_id)
            
        except Exception as e:
            self.logger.error(f"Error in alliance_disband: {e}")
            return {"success": False, "message": str(e)}