from datetime import datetime
from typing import Optional, Dict, Any, List
import logging


class AllianceDBManager:
    """
    연맹 DB 관리자
    
    테이블:
        - alliance: 연맹 기본 정보
        - alliance_member: 연맹 멤버
        - alliance_application: 가입 신청
    """
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    # ==================== 연맹 기본 정보 ====================

    async def create_alliance(self, alliance_id: int, name: str, leader_no: int, 
                               join_type: str = 'free') -> bool:
        """연맹 생성"""
        try:
            query = """
                INSERT INTO alliance (alliance_id, name, level, exp, leader_no, join_type, created_at, updated_at)
                VALUES ($1, $2, 1, 0, $3, $4, NOW(), NOW())
            """
            await self.db_manager.execute(query, alliance_id, name, leader_no, join_type)
            self.logger.info(f"Alliance created in DB: id={alliance_id}, name={name}")
            return True
        except Exception as e:
            self.logger.error(f"Error creating alliance in DB: {e}")
            return False

    async def get_alliance(self, alliance_id: int) -> Optional[Dict[str, Any]]:
        """연맹 정보 조회"""
        try:
            query = """
                SELECT alliance_id, name, level, exp, leader_no, join_type, created_at, updated_at
                FROM alliance
                WHERE alliance_id = $1
            """
            row = await self.db_manager.fetchrow(query, alliance_id)
            if row:
                return {
                    "alliance_id": row['alliance_id'],
                    "name": row['name'],
                    "level": row['level'],
                    "exp": row['exp'],
                    "leader_no": row['leader_no'],
                    "join_type": row['join_type'],
                    "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                    "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
                }
            return None
        except Exception as e:
            self.logger.error(f"Error getting alliance from DB: {e}")
            return None

    async def update_alliance(self, alliance_id: int, updates: Dict[str, Any]) -> bool:
        """연맹 정보 업데이트"""
        try:
            set_clauses = []
            values = []
            idx = 1
            
            for key, value in updates.items():
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            set_clauses.append(f"updated_at = NOW()")
            values.append(alliance_id)
            
            query = f"""
                UPDATE alliance
                SET {', '.join(set_clauses)}
                WHERE alliance_id = ${idx}
            """
            await self.db_manager.execute(query, *values)
            return True
        except Exception as e:
            self.logger.error(f"Error updating alliance in DB: {e}")
            return False

    async def delete_alliance(self, alliance_id: int) -> bool:
        """연맹 삭제"""
        try:
            query = "DELETE FROM alliance WHERE alliance_id = $1"
            await self.db_manager.execute(query, alliance_id)
            self.logger.info(f"Alliance deleted from DB: id={alliance_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting alliance from DB: {e}")
            return False

    async def get_all_alliances(self) -> List[Dict[str, Any]]:
        """모든 연맹 조회 (서버 시작 시 로드용)"""
        try:
            query = """
                SELECT alliance_id, name, level, exp, leader_no, join_type, created_at, updated_at
                FROM alliance
                ORDER BY alliance_id
            """
            rows = await self.db_manager.fetch(query)
            
            alliances = []
            for row in rows:
                alliances.append({
                    "alliance_id": row['alliance_id'],
                    "name": row['name'],
                    "level": row['level'],
                    "exp": row['exp'],
                    "leader_no": row['leader_no'],
                    "join_type": row['join_type'],
                    "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                    "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
                })
            
            return alliances
        except Exception as e:
            self.logger.error(f"Error getting all alliances from DB: {e}")
            return []

    async def get_max_alliance_id(self) -> int:
        """최대 연맹 ID 조회 (ID 카운터 복원용)"""
        try:
            query = "SELECT COALESCE(MAX(alliance_id), 0) as max_id FROM alliance"
            row = await self.db_manager.fetchrow(query)
            return row['max_id'] if row else 0
        except Exception as e:
            self.logger.error(f"Error getting max alliance id: {e}")
            return 0

    # ==================== 멤버 관리 ====================

    async def add_member(self, alliance_id: int, user_no: int, position: int, 
                          donated_exp: int = 0) -> bool:
        """멤버 추가"""
        try:
            query = """
                INSERT INTO alliance_member (alliance_id, user_no, position, donated_exp, joined_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (alliance_id, user_no) 
                DO UPDATE SET position = $3, donated_exp = $4
            """
            await self.db_manager.execute(query, alliance_id, user_no, position, donated_exp)
            return True
        except Exception as e:
            self.logger.error(f"Error adding member to DB: {e}")
            return False

    async def remove_member(self, alliance_id: int, user_no: int) -> bool:
        """멤버 제거"""
        try:
            query = "DELETE FROM alliance_member WHERE alliance_id = $1 AND user_no = $2"
            await self.db_manager.execute(query, alliance_id, user_no)
            return True
        except Exception as e:
            self.logger.error(f"Error removing member from DB: {e}")
            return False

    async def get_members(self, alliance_id: int) -> Dict[str, Dict]:
        """연맹 멤버 목록 조회"""
        try:
            query = """
                SELECT user_no, position, donated_exp, joined_at
                FROM alliance_member
                WHERE alliance_id = $1
            """
            rows = await self.db_manager.fetch(query, alliance_id)
            
            members = {}
            for row in rows:
                members[str(row['user_no'])] = {
                    "position": row['position'],
                    "donated_exp": row['donated_exp'],
                    "joined_at": row['joined_at'].isoformat() if row['joined_at'] else None
                }
            
            return members
        except Exception as e:
            self.logger.error(f"Error getting members from DB: {e}")
            return {}

    async def update_member(self, alliance_id: int, user_no: int, updates: Dict[str, Any]) -> bool:
        """멤버 정보 업데이트"""
        try:
            set_clauses = []
            values = []
            idx = 1
            
            for key, value in updates.items():
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            values.extend([alliance_id, user_no])
            
            query = f"""
                UPDATE alliance_member
                SET {', '.join(set_clauses)}
                WHERE alliance_id = ${idx} AND user_no = ${idx + 1}
            """
            await self.db_manager.execute(query, *values)
            return True
        except Exception as e:
            self.logger.error(f"Error updating member in DB: {e}")
            return False

    async def delete_all_members(self, alliance_id: int) -> bool:
        """연맹의 모든 멤버 삭제"""
        try:
            query = "DELETE FROM alliance_member WHERE alliance_id = $1"
            await self.db_manager.execute(query, alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting all members from DB: {e}")
            return False

    async def get_user_alliance(self, user_no: int) -> Optional[Dict[str, Any]]:
        """유저의 연맹 정보 조회"""
        try:
            query = """
                SELECT alliance_id, position, donated_exp, joined_at
                FROM alliance_member
                WHERE user_no = $1
            """
            row = await self.db_manager.fetchrow(query, user_no)
            if row:
                return {
                    "alliance_id": row['alliance_id'],
                    "position": row['position'],
                    "donated_exp": row['donated_exp'],
                    "joined_at": row['joined_at'].isoformat() if row['joined_at'] else None
                }
            return None
        except Exception as e:
            self.logger.error(f"Error getting user alliance from DB: {e}")
            return None

    # ==================== 가입 신청 관리 ====================

    async def add_application(self, alliance_id: int, user_no: int) -> bool:
        """가입 신청 추가"""
        try:
            query = """
                INSERT INTO alliance_application (alliance_id, user_no, applied_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (alliance_id, user_no) DO NOTHING
            """
            await self.db_manager.execute(query, alliance_id, user_no)
            return True
        except Exception as e:
            self.logger.error(f"Error adding application to DB: {e}")
            return False

    async def remove_application(self, alliance_id: int, user_no: int) -> bool:
        """가입 신청 제거"""
        try:
            query = "DELETE FROM alliance_application WHERE alliance_id = $1 AND user_no = $2"
            await self.db_manager.execute(query, alliance_id, user_no)
            return True
        except Exception as e:
            self.logger.error(f"Error removing application from DB: {e}")
            return False

    async def get_applications(self, alliance_id: int) -> Dict[str, Dict]:
        """가입 신청 목록 조회"""
        try:
            query = """
                SELECT user_no, applied_at
                FROM alliance_application
                WHERE alliance_id = $1
            """
            rows = await self.db_manager.fetch(query, alliance_id)
            
            applications = {}
            for row in rows:
                applications[str(row['user_no'])] = {
                    "applied_at": row['applied_at'].isoformat() if row['applied_at'] else None
                }
            
            return applications
        except Exception as e:
            self.logger.error(f"Error getting applications from DB: {e}")
            return {}

    async def delete_all_applications(self, alliance_id: int) -> bool:
        """연맹의 모든 가입 신청 삭제"""
        try:
            query = "DELETE FROM alliance_application WHERE alliance_id = $1"
            await self.db_manager.execute(query, alliance_id)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting all applications from DB: {e}")
            return False

    # ==================== 동기화 (Redis → DB) ====================

    async def sync_alliance_from_redis(self, alliance_info: Dict, members: Dict, 
                                        applications: Dict) -> bool:
        """Redis 데이터를 DB에 동기화"""
        try:
            alliance_id = alliance_info.get('alliance_id')
            
            # 연맹 정보 upsert
            query = """
                INSERT INTO alliance (alliance_id, name, level, exp, leader_no, join_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (alliance_id) 
                DO UPDATE SET 
                    name = $2, level = $3, exp = $4, leader_no = $5, 
                    join_type = $6, updated_at = NOW()
            """
            await self.db_manager.execute(
                query,
                alliance_id,
                alliance_info.get('name'),
                alliance_info.get('level', 1),
                alliance_info.get('exp', 0),
                alliance_info.get('leader_no'),
                alliance_info.get('join_type', 'free'),
                alliance_info.get('created_at', datetime.utcnow().isoformat())
            )
            
            # 기존 멤버 삭제 후 재삽입
            await self.delete_all_members(alliance_id)
            for user_no_str, member_data in members.items():
                await self.add_member(
                    alliance_id,
                    int(user_no_str),
                    member_data.get('position', 4),
                    member_data.get('donated_exp', 0)
                )
            
            # 기존 신청 삭제 후 재삽입
            await self.delete_all_applications(alliance_id)
            for user_no_str, app_data in applications.items():
                await self.add_application(alliance_id, int(user_no_str))
            
            self.logger.info(f"Alliance {alliance_id} synced to DB")
            return True
            
        except Exception as e:
            self.logger.error(f"Error syncing alliance to DB: {e}")
            return False

    # ==================== 서버 시작 시 로드 ====================

    async def load_all_to_redis(self, alliance_redis) -> int:
        """
        서버 시작 시 DB에서 모든 연맹 데이터를 Redis로 로드
        
        Returns:
            로드된 연맹 수
        """
        try:
            alliances = await self.get_all_alliances()
            loaded_count = 0
            
            for alliance_info in alliances:
                alliance_id = alliance_info['alliance_id']
                
                # 멤버 로드
                members = await self.get_members(alliance_id)
                
                # 가입 신청 로드
                applications = await self.get_applications(alliance_id)
                
                # Redis에 저장
                await alliance_redis.set_alliance_info(alliance_id, alliance_info)
                
                if members:
                    for user_no_str, member_data in members.items():
                        await alliance_redis.add_member(alliance_id, int(user_no_str), member_data)
                        # 유저 → 연맹 역참조 저장
                        await alliance_redis.set_user_alliance(int(user_no_str), {
                            "alliance_id": alliance_id,
                            "position": member_data.get('position', 4)
                        })
                
                if applications:
                    for user_no_str, app_data in applications.items():
                        await alliance_redis.add_application(alliance_id, int(user_no_str), app_data)
                
                # 이름 매핑
                await alliance_redis.set_alliance_name_mapping(alliance_info['name'], alliance_id)
                
                # 연맹 목록에 추가
                await alliance_redis.add_to_alliance_list(alliance_id)
                
                loaded_count += 1
            
            # ID 카운터 복원
            max_id = await self.get_max_alliance_id()
            if max_id > 0:
                await alliance_redis.redis_client.set(
                    alliance_redis._get_alliance_id_counter_key(), 
                    max_id
                )
            
            self.logger.info(f"Loaded {loaded_count} alliances from DB to Redis")
            return loaded_count
            
        except Exception as e:
            self.logger.error(f"Error loading alliances to Redis: {e}")
            return 0