import json
from datetime import datetime
from typing import Optional, List, Dict, Any


class CombatRedisManager:
    """
    전투/행군/맵 전용 Redis 관리자

    Key 구조:
        map:positions                        Hash  {user_no -> "x,y"}
        completion_queue:march               ZSet  score=arrival_time, member=march_id
        completion_queue:march_return        ZSet  score=return_time,  member=march_id
        march:metadata:{march_id}            String (JSON)
        battle:{battle_id}                   Hash  전투 상태
        battle:active                        Set   활성 battle_id 목록
        user_data:{user_no}:march            String (JSON) 유저별 행군 목록
    """

    MAP_POSITIONS_KEY = "map:positions"
    MARCH_QUEUE_KEY = "completion_queue:march"
    MARCH_RETURN_QUEUE_KEY = "completion_queue:march_return"
    BATTLE_ACTIVE_KEY = "battle:active"

    def __init__(self, redis_client):
        self.redis = redis_client

    # ─────────────────────────────────────────────
    # 맵 위치 관련
    # ─────────────────────────────────────────────

    async def get_position(self, user_no: int) -> Optional[Dict[str, int]]:
        raw = await self.redis.hget(self.MAP_POSITIONS_KEY, str(user_no))
        if raw is None:
            return None
        x, y = raw.split(",")
        return {"x": int(x), "y": int(y)}

    async def set_position(self, user_no: int, x: int, y: int) -> bool:
        await self.redis.hset(self.MAP_POSITIONS_KEY, str(user_no), f"{x},{y}")
        return True

    async def get_all_positions(self) -> Dict[int, Dict[str, int]]:
        """전체 유저 좌표 반환"""
        raw = await self.redis.hgetall(self.MAP_POSITIONS_KEY)
        result = {}
        for user_no_str, pos_str in raw.items():
            x, y = pos_str.split(",")
            result[int(user_no_str)] = {"x": int(x), "y": int(y)}
        return result

    async def get_nearby_positions(self, cx: int, cy: int, radius: int) -> List[Dict]:
        """반경 내 유저 목록"""
        all_pos = await self.get_all_positions()
        nearby = []
        for user_no, pos in all_pos.items():
            if abs(pos["x"] - cx) <= radius and abs(pos["y"] - cy) <= radius:
                nearby.append({"user_no": user_no, "x": pos["x"], "y": pos["y"]})
        return nearby

    # ─────────────────────────────────────────────
    # 행군 큐 (출진)
    # ─────────────────────────────────────────────

    async def add_march_to_queue(self, march_id: int, arrival_time: datetime) -> bool:
        score = arrival_time.timestamp()
        await self.redis.zadd(self.MARCH_QUEUE_KEY, {str(march_id): score})
        return True

    async def remove_march_from_queue(self, march_id: int) -> bool:
        await self.redis.zrem(self.MARCH_QUEUE_KEY, str(march_id))
        return True

    async def get_pending_march_arrivals(self, current_time: Optional[datetime] = None) -> List[int]:
        """도착 시간이 지난 행군 ID 목록"""
        now = (current_time or datetime.utcnow()).timestamp()
        members = await self.redis.zrangebyscore(self.MARCH_QUEUE_KEY, "-inf", now)
        return [int(m) for m in members]

    # ─────────────────────────────────────────────
    # 귀환 큐 (return)
    # ─────────────────────────────────────────────

    async def add_march_return_to_queue(self, march_id: int, return_time: datetime) -> bool:
        score = return_time.timestamp()
        await self.redis.zadd(self.MARCH_RETURN_QUEUE_KEY, {str(march_id): score})
        return True

    async def remove_march_return_from_queue(self, march_id: int) -> bool:
        await self.redis.zrem(self.MARCH_RETURN_QUEUE_KEY, str(march_id))
        return True

    async def get_pending_march_returns(self, current_time: Optional[datetime] = None) -> List[int]:
        """귀환 시간이 지난 행군 ID 목록"""
        now = (current_time or datetime.utcnow()).timestamp()
        members = await self.redis.zrangebyscore(self.MARCH_RETURN_QUEUE_KEY, "-inf", now)
        return [int(m) for m in members]

    # ─────────────────────────────────────────────
    # 행군 메타데이터
    # ─────────────────────────────────────────────

    async def set_march_metadata(self, march_id: int, metadata: Dict[str, Any]) -> bool:
        key = f"march:metadata:{march_id}"
        await self.redis.set(key, json.dumps(metadata), ex=86400)  # 24h TTL
        return True

    async def get_march_metadata(self, march_id: int) -> Optional[Dict[str, Any]]:
        key = f"march:metadata:{march_id}"
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def delete_march_metadata(self, march_id: int) -> bool:
        key = f"march:metadata:{march_id}"
        await self.redis.delete(key)
        return True

    # ─────────────────────────────────────────────
    # 유저별 행군 목록 캐시
    # ─────────────────────────────────────────────

    async def get_user_marches(self, user_no: int) -> Optional[List[Dict]]:
        key = f"user_data:{user_no}:march"
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_user_marches(self, user_no: int, marches: List[Dict]) -> bool:
        key = f"user_data:{user_no}:march"
        await self.redis.set(key, json.dumps(marches), ex=3600)
        return True

    async def invalidate_user_marches(self, user_no: int) -> bool:
        key = f"user_data:{user_no}:march"
        await self.redis.delete(key)
        return True

    # ─────────────────────────────────────────────
    # 전투 상태 (Hash per battle)
    # ─────────────────────────────────────────────

    async def set_battle_state(self, battle_id: int, state: Dict[str, Any]) -> bool:
        key = f"battle:{battle_id}"
        serialized = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                      for k, v in state.items()}
        await self.redis.hset(key, mapping=serialized)
        await self.redis.expire(key, 86400)
        return True

    async def get_battle_state(self, battle_id: int) -> Optional[Dict[str, Any]]:
        key = f"battle:{battle_id}"
        raw = await self.redis.hgetall(key)
        if not raw:
            return None
        result = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    async def update_battle_field(self, battle_id: int, field: str, value: Any) -> bool:
        key = f"battle:{battle_id}"
        serialized = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        await self.redis.hset(key, field, serialized)
        return True

    async def delete_battle_state(self, battle_id: int) -> bool:
        key = f"battle:{battle_id}"
        await self.redis.delete(key)
        return True

    # ─────────────────────────────────────────────
    # 활성 전투 Set
    # ─────────────────────────────────────────────

    async def add_active_battle(self, battle_id: int) -> bool:
        await self.redis.sadd(self.BATTLE_ACTIVE_KEY, str(battle_id))
        return True

    async def remove_active_battle(self, battle_id: int) -> bool:
        await self.redis.srem(self.BATTLE_ACTIVE_KEY, str(battle_id))
        return True

    async def get_active_battles(self) -> List[int]:
        members = await self.redis.smembers(self.BATTLE_ACTIVE_KEY)
        return [int(m) for m in members]

    # ─────────────────────────────────────────────
    # NPC 인스턴스 관리
    # ─────────────────────────────────────────────

    MAP_NPCS_KEY = "map:npcs"
    NPC_RESPAWN_QUEUE_KEY = "completion_queue:npc_respawn"

    async def get_all_npcs(self) -> Dict[int, Dict]:
        raw = await self.redis.hgetall(self.MAP_NPCS_KEY)
        result = {}
        for npc_id_str, val in raw.items():
            try:
                result[int(npc_id_str)] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    async def get_npc(self, npc_id: int) -> Optional[Dict]:
        raw = await self.redis.hget(self.MAP_NPCS_KEY, str(npc_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def set_npc(self, npc_id: int, npc_data: Dict) -> bool:
        await self.redis.hset(self.MAP_NPCS_KEY, str(npc_id), json.dumps(npc_data))
        return True

    async def set_npc_alive(self, npc_id: int, alive: bool) -> bool:
        npc = await self.get_npc(npc_id)
        if npc is None:
            return False
        npc['alive'] = alive
        if alive:
            npc['respawn_at'] = None
        await self.set_npc(npc_id, npc)
        return True

    async def add_npc_respawn_to_queue(self, npc_id: int, respawn_time: datetime) -> bool:
        score = respawn_time.timestamp()
        await self.redis.zadd(self.NPC_RESPAWN_QUEUE_KEY, {str(npc_id): score})
        return True

    async def get_pending_npc_respawns(self, current_time: Optional[datetime] = None) -> List[int]:
        now = (current_time or datetime.utcnow()).timestamp()
        members = await self.redis.zrangebyscore(self.NPC_RESPAWN_QUEUE_KEY, "-inf", now)
        return [int(m) for m in members]

    async def remove_npc_respawn_from_queue(self, npc_id: int) -> bool:
        await self.redis.zrem(self.NPC_RESPAWN_QUEUE_KEY, str(npc_id))
        return True
