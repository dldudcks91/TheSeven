import json
import random
import logging
from typing import Dict, Optional


VALID_BF_IDS = {1, 2, 3}
MAP_SIZE = 100


class BattlefieldManager:
    """
    전장(Battlefield) 시스템 관리자

    전장 1~3: 독립적인 100×100 세계 맵 인스턴스.
    유저는 1개의 전장에만 참여(성 투입) 가능.
    참여하지 않은 전장은 관전자로 접근 가능.

    Redis 키:
        battlefield:{bf_id}:members      Hash  {user_no → JSON}
        battlefield:{bf_id}:subscribers  Set   battlefield_tick 수신 대상
        battlefield:{bf_id}:battles      Set   전장 내 진행 중 battle_id
        user_data:{user_no}:battlefield  String  참여 중인 bf_id
    """

    def __init__(self, db_manager, redis_manager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.user_no: Optional[int] = None
        self.data: Dict = {}
        self.websocket_manager = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _format(self, success: bool, message: str, data: dict = None) -> Dict:
        return {"success": success, "message": message, "data": data or {}}

    # ─────────────────────────────────────────────
    # 9050 battlefield_list
    # ─────────────────────────────────────────────

    async def battlefield_list(self) -> Dict:
        """전장 1~3 현황 (참여자 수, 구독자 수)"""
        combat_rm = self.redis_manager.get_combat_manager()
        result = []
        for bf_id in sorted(VALID_BF_IDS):
            member_count = await combat_rm.bf_get_member_count(bf_id)
            subscriber_count = await combat_rm.bf_get_subscriber_count(bf_id)
            result.append({
                "bf_id": bf_id,
                "member_count": member_count,
                "subscriber_count": subscriber_count,
            })
        return self._format(True, "OK", {"battlefields": result})

    # ─────────────────────────────────────────────
    # 9051 battlefield_join
    # ─────────────────────────────────────────────

    async def battlefield_join(self) -> Dict:
        """전장 참여 (성 투입). data: {bf_id}"""
        user_no = self.user_no
        bf_id = int(self.data.get("bf_id", 0))

        if bf_id not in VALID_BF_IDS:
            return self._format(False, "유효하지 않은 전장 ID")

        combat_rm = self.redis_manager.get_combat_manager()

        current_bf = await combat_rm.get_user_battlefield(user_no)
        if current_bf is not None:
            if current_bf == bf_id:
                return self._format(False, "이미 해당 전장에 참여 중")
            return self._format(False, f"전장 {current_bf}에 참여 중. 후퇴 후 재참여 가능")

        castle_x = random.randint(0, MAP_SIZE - 1)
        castle_y = random.randint(0, MAP_SIZE - 1)

        # Redis 업데이트
        await combat_rm.bf_join(bf_id, user_no, castle_x, castle_y)

        # DB 기록 (영속성)
        bf_dm = self.db_manager.get_battlefield_manager()
        bf_dm.join_battlefield(user_no, bf_id, castle_x, castle_y)
        self.db_manager.commit()

        # 기존 구독자에게 join 이벤트 브로드캐스트
        await self._broadcast_bf(bf_id, {
            "type": "battlefield_join",
            "bf_id": bf_id,
            "user_no": user_no,
            "castle_x": castle_x,
            "castle_y": castle_y,
        }, exclude=user_no)

        return self._format(True, "전장 참여 완료", {
            "bf_id": bf_id,
            "castle_x": castle_x,
            "castle_y": castle_y,
        })

    # ─────────────────────────────────────────────
    # 9052 battlefield_retreat
    # ─────────────────────────────────────────────

    async def battlefield_retreat(self) -> Dict:
        """전장 후퇴. (병력 조건 체크는 추후 추가 예정)"""
        user_no = self.user_no
        combat_rm = self.redis_manager.get_combat_manager()

        bf_id = await combat_rm.get_user_battlefield(user_no)
        if bf_id is None:
            return self._format(False, "참여 중인 전장 없음")

        # 브로드캐스트 먼저 (구독자 목록이 삭제되기 전)
        subscribers = await combat_rm.bf_get_subscribers(bf_id)

        # Redis 업데이트 (members + subscribers + user_bf 키 삭제)
        await combat_rm.bf_retreat(bf_id, user_no)

        # DB 업데이트
        bf_dm = self.db_manager.get_battlefield_manager()
        bf_dm.retreat_battlefield(user_no)
        self.db_manager.commit()

        # 잔여 구독자에게 retreat 이벤트
        await self._notify_list(subscribers, {
            "type": "battlefield_retreat",
            "bf_id": bf_id,
            "user_no": user_no,
        }, exclude=user_no)

        return self._format(True, "전장 후퇴 완료", {"bf_id": bf_id})

    # ─────────────────────────────────────────────
    # 9053 battlefield_info
    # ─────────────────────────────────────────────

    async def battlefield_info(self) -> Dict:
        """전장 스냅샷 (참여자 위치 + 진행 중 전투 목록). data: {bf_id}"""
        bf_id = int(self.data.get("bf_id", 0))
        if bf_id not in VALID_BF_IDS:
            return self._format(False, "유효하지 않은 전장 ID")

        combat_rm = self.redis_manager.get_combat_manager()

        members = await combat_rm.bf_get_members(bf_id)
        battle_ids = await combat_rm.bf_get_battles(bf_id)

        battles = []
        for bid in battle_ids:
            state = await combat_rm.get_battle_state(bid)
            if not state:
                continue
            atk_max = int(state.get("atk_max_hp", 1)) or 1
            def_max = int(state.get("def_max_hp", 1)) or 1
            atk_hp = int(state.get("atk_hp", atk_max))
            def_hp = int(state.get("def_hp", def_max))
            battles.append({
                "battle_id": bid,
                "x": int(state.get("to_x", 0)),
                "y": int(state.get("to_y", 0)),
                "atk_hp_pct": int(atk_hp / atk_max * 100),
                "def_hp_pct": int(def_hp / def_max * 100),
                "round": int(state.get("round", 0)),
                "attacker_no": int(state.get("attacker_no", 0)),
                "defender_no": int(state.get("defender_no", 0)),
            })

        return self._format(True, "OK", {
            "bf_id": bf_id,
            "members": {str(un): data for un, data in members.items()},
            "battles": battles,
        })

    # ─────────────────────────────────────────────
    # 9054 battlefield_watch
    # ─────────────────────────────────────────────

    async def battlefield_watch(self) -> Dict:
        """전장 관전 시작 (구독 등록 + 현재 스냅샷 반환). data: {bf_id}"""
        bf_id = int(self.data.get("bf_id", 0))
        if bf_id not in VALID_BF_IDS:
            return self._format(False, "유효하지 않은 전장 ID")

        combat_rm = self.redis_manager.get_combat_manager()
        await combat_rm.bf_watch(bf_id, self.user_no)

        # 현재 스냅샷을 응답으로 반환 (battlefield_info 재사용)
        return await self.battlefield_info()

    # ─────────────────────────────────────────────
    # 9055 battlefield_unwatch
    # ─────────────────────────────────────────────

    async def battlefield_unwatch(self) -> Dict:
        """전장 관전 종료 (구독 해제). data: {bf_id}"""
        bf_id = int(self.data.get("bf_id", 0))
        if bf_id not in VALID_BF_IDS:
            return self._format(False, "유효하지 않은 전장 ID")

        combat_rm = self.redis_manager.get_combat_manager()

        # 참여 중인 전장은 관전 해제 불가 (bf_join 시 자동 구독됨)
        current_bf = await combat_rm.get_user_battlefield(self.user_no)
        if current_bf == bf_id:
            return self._format(False, "참여 중인 전장은 관전 해제 불가. 후퇴 후 가능")

        await combat_rm.bf_unwatch(bf_id, self.user_no)
        return self._format(True, "관전 종료", {"bf_id": bf_id})

    # ─────────────────────────────────────────────
    # 내부 헬퍼
    # ─────────────────────────────────────────────

    async def _broadcast_bf(self, bf_id: int, msg: dict, exclude: int = None):
        """전장 전체 구독자에게 JSON 메시지 전송"""
        if not self.websocket_manager:
            return
        combat_rm = self.redis_manager.get_combat_manager()
        subscribers = await combat_rm.bf_get_subscribers(bf_id)
        await self._notify_list(subscribers, msg, exclude=exclude)

    async def _notify_list(self, user_nos: list, msg: dict, exclude: int = None):
        if not self.websocket_manager:
            return
        payload = json.dumps(msg)
        for user_no in user_nos:
            if exclude and user_no == exclude:
                continue
            try:
                await self.websocket_manager.send_personal_message(payload, user_no)
            except Exception as e:
                self.logger.error(f"BattlefieldManager WS error user={user_no}: {e}")
