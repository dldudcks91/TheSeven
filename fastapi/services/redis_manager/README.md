# services/redis_manager - Redis 레이어

## 역할

Redis와의 모든 통신을 담당하는 레이어. 게임 데이터 캐싱과 시간 기반 Task Queue 두 가지 목적을 처리.

- **캐시**: 유저 게임 데이터(건물/유닛/자원 등)를 Redis Hash에 저장 → 빠른 읽기/쓰기
- **Task Queue**: 건설/훈련/연구 완료 시각을 Redis Sorted Set에 저장 → TaskWorker가 폴링하며 처리

---

## 기반 클래스 (Base Classes)

### base_redis_cache_manager.py - BaseRedisCacheManager

**역할**: Redis 캐싱 전반을 담당하는 추상 기반 클래스

**주요 기능**:

**일반 캐시 (String/JSON)**:
- `set_data(key, data, expire_time)`: JSON 직렬화 후 `SETEX`
- `get_data(key)`: JSON 역직렬화
- `delete_data(key)`: `DEL`

**Hash 캐시**:
- `set_hash_data(hash_key, data, expire_time)`: 딕셔너리를 Hash 필드로 저장 (각 값 JSON 직렬화) → Pipeline 사용
- `get_hash_data(hash_key)`: `HGETALL` → JSON 역직렬화
- `set_hash_field(hash_key, field, value)`: `HSET` + TTL 갱신 (Pipeline)
- `get_hash_field(hash_key, field)`: `HGET`
- `delete_hash_field(hash_key, field)`: `HDEL`
- `get_hash_fields(hash_key, fields)`: `HMGET` 멀티 필드 조회

**원자적 증감**:
- `increment_data(key, amount)`: `INCRBY` → 단일 키 원자적 증감
- `decrement_data(key, amount)`: `DECRBY`
- `increment_hash_field(hash_key, field, amount)`: `HINCRBY` → Hash 필드 원자적 증감

**배치 작업**:
- `set_multiple(data_dict, expire_time)`: Pipeline으로 다수 키 일괄 설정
- `get_multiple(keys)`: `MGET` 다수 키 일괄 조회
- `delete_multiple(keys)`: 다수 키 일괄 삭제

**패턴 기반**:
- `delete_by_pattern(pattern)`: scan_iter로 패턴 매칭 후 일괄 삭제
- `get_keys_by_pattern(pattern)`: 패턴 매칭 키 목록 반환

**유틸**:
- `exists(key)`: 키 존재 여부
- `get_ttl(key)`: TTL 조회
- `extend_ttl(key, expire_time)`: TTL 연장
- `get_user_data_hash_key(user_no)`: `user_data:{user_no}:{cache_type}` 키 생성
- `get_user_data_meta_key(user_no)`: 메타데이터 키 생성

**키 네이밍**: `cache_type`은 `CacheType` Enum에서 가져오며 `user_data:{user_no}:{cache_type}` 패턴 사용

---

### base_redis_task_manager.py - BaseRedisTaskManager

**역할**: Sorted Set 기반 Task Queue 관리 추상 기반 클래스

**자료구조**: Redis Sorted Set
- Key: `completion_queue:{task_type}`
- Member: `{user_no}:{task_id}` 또는 `{user_no}:{task_id}:{sub_id}`
- Score: 완료 예정 시각의 UNIX timestamp

**주요 메서드**:
- `add_to_queue(user_no, task_id, completion_time, sub_id, metadata)`: `ZADD` + 메타데이터 Hash 저장
- `get_completed_tasks(current_time)`: `ZRANGEBYSCORE(0, now)` → 완료된 작업 목록 반환
- `remove_from_queue(user_no, task_id, sub_id)`: `ZREM` + 메타데이터 `DEL`
- `update_completion_time(user_no, task_id, new_time)`: `ZREM` 후 `ZADD` (시간 변경)
- `get_completion_time(user_no, task_id)`: `ZSCORE` → 완료 시각 반환
- `get_user_tasks(user_no)`: 특정 유저의 진행 중 모든 작업 조회
- `get_queue_status()`: `{total, completed, pending}` 상태 통계
- `cleanup_old_entries(days_old)`: 오래된 항목 정리 (`ZREMRANGEBYSCORE`)

**메타데이터 저장**: 작업 부가 정보를 별도 Hash(`completion_queue:{task_type}:metadata:{member}`)에 저장, TTL 86400초

---

## 파일 목록 (도메인별 Manager)

### RedisManager.py

**역할**: 모든 도메인 Redis Manager의 중앙 접근점 (Facade 패턴)

**구현 방식**:
- `get_building_manager()`, `get_unit_manager()`, ... 게터 메서드
- Lazy initialization (싱글톤): 첫 호출 시 인스턴스 생성, 이후 재사용
- `redis_client`를 공유 → 모두 동일한 Connection Pool 사용

```python
redis_manager = RedisManager(redis_client)
building_redis = redis_manager.get_building_manager()
```

**관리하는 Manager 목록**:
`BuildingRedisManager, UnitRedisManager, ResearchRedisManager, BuffRedisManager,
ResourceRedisManager, ItemRedisManager, MissionRedisManager, ShopRedisManager,
AllianceRedisManager, NationRedisManager`

---

### building_redis_manager.py - BuildingRedisManager

**역할**: 건물 캐시 관리

**Redis 키**: `user_data:{user_no}:building` (Hash)
- 필드: `building_idx` (string)
- 값: JSON 직렬화된 건물 데이터

**주요 메서드**:
- `get_cached_buildings(user_no)`: 전체 건물 Hash 조회
- `get_cached_building(user_no, building_idx)`: 특정 건물 Hash 필드 조회
- `cache_user_buildings_data(user_no, buildings_data)`: 건물 데이터 Hash 저장
- `update_cached_building(user_no, building_idx, data)`: 특정 건물 Hash 필드 업데이트
- `delete_cached_building(user_no, building_idx)`: 특정 건물 Hash 필드 삭제

---

### unit_redis_manager.py - UnitRedisManager

**역할**: 유닛 캐시 + 훈련 Task Queue 관리

**Redis 키**:
- 캐시: `user_data:{user_no}:unit` (Hash)
- Task Queue: `completion_queue:unit` (Sorted Set)

**주요 메서드**:
- `get_cached_units(user_no)`: 유닛 캐시 조회
- `get_completed_units()`: 완료된 훈련 작업 조회 (`get_completed_tasks()` 래핑)
- `register_active_tasks_to_queue(user_no, units_data)`: 로그인 시 진행 중 작업 Queue 복원
  - 서버 재시작 후 진행 중이던 훈련 작업의 완료 시각을 Queue에 재등록

---

### research_redis_manager.py - ResearchRedisManager

**역할**: 연구 캐시 + 연구 Task Queue 관리

**Redis 키**:
- 캐시: `user_data:{user_no}:research` (Hash)
- Task Queue: `completion_queue:research` (Sorted Set)

---

### resource_redis_manager.py - ResourceRedisManager

**역할**: 자원 캐시 + **원자적 소모 (Lua Script)**

**Redis 키**: `user_data:{user_no}:resources` (Hash)
- 필드: `food, wood, stone, gold, ruby`
- 값: 정수 문자열 (JSON 아님 - `HINCRBY` 사용을 위해)

**핵심 메서드**:
- `get_cached_all_resources(user_no)`: `HGETALL` → 자원 딕셔너리 반환
- `atomic_consume(user_no, costs)`: **Lua Script**로 원자적 검사+차감
  - 모든 자원이 충분한지 확인 후 한 번에 차감
  - Race Condition 방지 (다수 동시 요청에서도 안전)
  - 반환: `{success: True, remaining: {...}}` or `{success: False, reason: "insufficient", shortage: {...}}`
- `produce_resources(user_no, gains)`: `HINCRBY`로 자원 증가
- `change_resource_amount(user_no, resource_type, amount)`: 단일 자원 `HINCRBY`
- `cache_user_resources_data(user_no, resources_dict)`: 전체 자원 Hash 저장

**Dirty Flag**: `sync_pending:resources` Set에 user_no 추가 (변경 시 자동)

---

### buff_redis_manager.py - BuffRedisManager

**역할**: 버프 캐시 관리

**Redis 키**: `user_data:{user_no}:buff` (Hash)

---

### item_redis_manager.py - ItemRedisManager

**역할**: 아이템 인벤토리 캐시 관리

**Redis 키**: `user_data:{user_no}:item` (Hash, item_idx → JSON)

**Dirty Flag 특이사항**: 변경 시 `sync_pending:item` Set에 `{user_no}:{item_idx}` 형태로 저장
→ ItemSyncWorker가 개별 아이템 단위로 처리

---

### mission_redis_manager.py - MissionRedisManager

**역할**: 미션 진행 상태 캐시 관리

**Redis 키**: `user_data:{user_no}:mission` (Hash, mission_idx → JSON)

---

### shop_redis_manager.py - ShopRedisManager

**역할**: 상점 현재 진열 아이템 캐시 관리

---

### alliance_redis_manager.py - AllianceRedisManager

**역할**: 연맹 데이터 캐시 관리

**Redis 키 구조**:
```
alliance:{alliance_id}:info           # 연맹 기본 정보 (Hash)
alliance:{alliance_id}:members        # 멤버 목록 (Hash, user_no → JSON)
alliance:{alliance_id}:applications   # 신청자 (Hash, user_no → JSON)
alliance:{alliance_id}:research       # 연맹 연구 (Hash, research_idx → JSON)
```

**주요 메서드**:
- `get_alliance_info(alliance_id)`: 연맹 기본 정보
- `get_members(alliance_id)`: 멤버 전체
- `get_applications(alliance_id)`: 신청자 전체
- `get_all_research(alliance_id)`: 연맹 연구 전체

**Dirty Flag**: `sync_pending:alliance` Set에 `alliance_id` 저장

---

### hero_redis_manager.py - HeroRedisManager

**역할**: 영웅 데이터 캐시 관리

---

### nation_redis_manager.py - NationRedisManager

**역할**: 국가 통계 캐시 관리

---

### redis_types.py

**역할**: `CacheType`, `TaskType` Enum 정의

```python
class CacheType(Enum):
    BUILDING = "building"
    UNIT = "unit"
    RESEARCH = "research"
    RESOURCE = "resources"
    BUFF = "buff"
    ITEM = "item"
    MISSION = "mission"
    SHOP = "shop"
    ALLIANCE = "alliance"

class TaskType(Enum):
    UNIT = "unit"
    RESEARCH = "research"
    BUFF = "buff"
    BUILDING = "building"
```

---

### redis_data_checker.py

**역할**: Redis 데이터 디버깅/검사 유틸리티

---

## Redis 키 전체 요약

| 키 패턴 | 자료구조 | 용도 |
|---------|----------|------|
| `user_data:{user_no}:building` | Hash | 건물 캐시 |
| `user_data:{user_no}:unit` | Hash | 유닛 캐시 |
| `user_data:{user_no}:research` | Hash | 연구 캐시 |
| `user_data:{user_no}:resources` | Hash | 자원 캐시 (정수값) |
| `user_data:{user_no}:buff` | Hash | 버프 캐시 |
| `user_data:{user_no}:item` | Hash | 아이템 캐시 |
| `user_data:{user_no}:mission` | Hash | 미션 캐시 |
| `sync_pending:{category}` | Set | Dirty flag (동기화 대기 user_no 목록) |
| `completion_queue:{task_type}` | Sorted Set | Task 완료 Queue (score = timestamp) |
| `completion_queue:{task_type}:metadata:{member}` | Hash | Task 메타데이터 |
| `alliance:{alliance_id}:info` | Hash | 연맹 기본 정보 |
| `alliance:{alliance_id}:members` | Hash | 연맹 멤버 |
| `alliance:{alliance_id}:applications` | Hash | 가입 신청자 |
| `alliance:{alliance_id}:research` | Hash | 연맹 연구 |
