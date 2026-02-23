# services/game - 게임 도메인 레이어

## 역할

게임 비즈니스 로직을 담당하는 레이어. 각 게임 시스템(건물, 연구, 유닛 등)을 독립적인 Manager 클래스로 구현. 모든 Manager는 Redis를 주 저장소로 사용하고 DB는 초기 캐시 로드와 신규 레코드 생성에만 사용.

---

## 공통 패턴

### 1. Manager 생성 패턴

모든 게임 Manager는 동일한 생성자 시그니처를 가짐:

```python
class XxxManager:
    def __init__(self, db_manager: DBManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self._user_no = None
        self._data = None
```

`APIManager`가 인스턴스 생성 후 `user_no`와 `data`를 setter로 주입.

### 2. 데이터 조회 패턴 (Cache-Aside / Redis-First)

```
1. 메모리 캐시(_cached_xxx) 확인
2. Redis에서 조회 (redis_manager.get_xxx_manager().get_cached_xxx())
3. Redis 미스 → DB에서 조회 후 Redis에 캐싱
```

### 3. 데이터 쓰기 패턴

```
Redis 갱신 → sync_pending:{category} Set에 user_no 추가 (dirty flag)
→ SyncWorker가 주기적으로 dirty flag 감지 → MySQL에 동기화
```

건물 최초 생성(신규 레코드)은 예외적으로 DB 직접 삽입 후 Redis 동기화.

### 4. 응답 형식 통일

```python
{"success": True/False, "message": "...", "data": {}}
```

### 5. 매니저 간 호출

Manager는 다른 Manager를 직접 import해 사용 가능. 지연 import로 순환 참조 방지:
```python
def _get_mission_manager(self):
    from services.game.MissionManager import MissionManager
    return MissionManager(self.db_manager, self.redis_manager)
```

---

## 파일 목록

### ResourceManager.py

**역할**: 5종 자원 (food, wood, stone, gold, ruby) 관리

**핵심 메서드**:
- `resource_info()`: 자원 조회 (api_code: 1011)
- `consume_resources(user_no, costs)`: **원자적** 자원 차감 (Lua Script 사용)
  - Race Condition 방지. `atomic_consume` → 검사+차감이 하나의 원자 연산
  - 반환: `{success, remaining, consumed}` 또는 `{success: False, reason: "insufficient", shortage}`
- `produce_resources(user_no, gains)`: 자원 생산/획득
- `add_resource(user_no, resource_type, amount)`: 단일 자원 추가 (하위 호환)
- `check_require_resources()`: **UI 미리보기 전용** (실제 소모 시 사용 금지 - Race Condition 위험)

**Redis 키**: `user_data:{user_no}:resources` (Hash)
**Dirty Flag**: `sync_pending:resources` Set에 user_no 추가

---

### BuildingManager.py

**역할**: 건물 건설/업그레이드/취소 관리

**핵심 메서드**:
- `building_info()`: 건물 조회 (api_code: 2001)
- `building_create()`: 최초 건설 (api_code: 2002) - DB 직접 삽입 후 Redis 동기화
- `building_upgrade()`: 업그레이드 시작 (api_code: 2003) - Redis만 업데이트
- `building_finish()`: 완료 처리 (api_code: 2004) - Redis 업데이트 + MissionManager 호출
- `building_cancel()`: 취소 + 자원 환불 (api_code: 2005)
- `finish_all_completed_buildings()`: end_time 지난 건물 일괄 완료 (api_code: 2006)

**상태값**: `0` = idle, `1` = 건설 중, `2` = 업그레이드 중
**Redis 키**: `user_data:{user_no}:building` (Hash, building_idx → JSON)
**상수**: `MAX_LEVEL = 10`, `AVAILABLE_BUILDINGS = [101, 201, 301, 401]`

**건설 시간 버프 적용**: `_apply_building_buffs()` → BuffManager에서 `building_speed` 타입 버프 조회 → 최대 90% 단축

---

### ResearchManager.py

**역할**: 연구 테크트리 관리

**핵심 메서드**:
- `research_info()`: 연구 정보 조회 (api_code: 3001)
- `research_start()`: 연구 시작 (api_code: 3002) - 비용 차감 → Redis Task Queue 등록
- `research_finish()`: 연구 완료 (api_code: 3003) - 버프 활성화 포함
- `research_cancel()`: 연구 취소 (api_code: 3004)

**특이사항**: 연구 완료 시 `research_info.csv`의 `buff_idx`에 해당하는 영구 버프를 `BuffManager`로 활성화.

---

### UnitManager.py

**역할**: 유닛 훈련/업그레이드 관리

**핵심 메서드**:
- `unit_info()`: 유닛 정보 조회 (api_code: 4001)
- `unit_train()`: 유닛 훈련 시작 (api_code: 4002) - Redis Task Queue에 완료 시각 등록
- `unit_upgrade()`: 유닛 업그레이드 (api_code: 4003)
- `unit_finish()`: 훈련 완료 처리 - **TaskWorker**에서 자동 호출됨
- `get_completed_units_for_worker()`: TaskWorker용 완료된 유닛 작업 조회

**Redis Task Queue**: `completion_queue:unit` (Sorted Set, score = 완료 timestamp)
- 멤버 키: `{user_no}:{unit_type}:{unit_idx}`

**훈련 완료 흐름**: TaskWorker(1초 주기) → `get_completed_units_for_worker()` → `unit_finish()` → WebSocket 알림

---

### BuffManager.py

**역할**: 임시/영구 버프 관리

**구분**:
- 임시 버프: `start_time`, `end_time` 있음 (아이템 사용, 상점 구매 등)
- 영구 버프: 연구 완료로 활성화

**핵심 메서드**:
- `buff_info()`: 버프 정보 조회 (api_code: 1012)
- `get_total_buffs_by_type(user_no, buff_type)`: 특정 타입의 버프 합산 - BuildingManager 등이 시간 계산 시 사용

**버프 분류**: `buff_type, effect_type, target_type, target_sub_type, stat_type, value_type`

---

### MissionManager.py

**역할**: 미션/퀘스트 시스템 관리

**핵심 메서드**:
- `mission_info()`: 미션 정보 조회 (api_code: 5001)
- `mission_claim()`: 보상 수령 (api_code: 5002) - 자원/아이템 지급
- `check_building_missions(building_idx)`: 건물 완료 시 관련 미션 체크 - BuildingManager가 호출

**미션 인덱스 활용**: `GameDataManager.REQUIRE_CONFIGS['mission_index']['building'][building_idx]`
→ 해당 building_idx와 연관된 미션 ID 목록 즉시 조회 (역인덱스)

**카테고리**: `building, unit, research, hero, battle, resource`

---

### ItemManager.py

**역할**: 아이템 인벤토리 관리

**핵심 메서드**:
- `item_info()`: 인벤토리 조회 (api_code: 6001)
- `item_get()`: 아이템 획득 (api_code: 6002)
- `item_use()`: 아이템 사용 (api_code: 6003) - item_info.csv의 category/value로 효과 적용

**Redis 키**: `user_data:{user_no}:item` (Hash, item_idx → JSON)
**Dirty Flag**: `sync_pending:item` Set에 `{user_no}:{item_idx}` 형태로 저장 (아이템은 개별 변경 추적)

---

### ShopManager.py

**역할**: 상점 아이템 구매/새로고침 관리

**핵심 메서드**:
- `shop_info()`: 현재 상점 아이템 조회 (api_code: 6011)
- `shop_refresh()`: 상점 새로고침 (api_code: 6012) - shop_info.csv의 weight 기반 랜덤 생성
- `shop_buy()`: 아이템 구매 (api_code: 6013)

---

### HeroManager.py

**역할**: 영웅 생성/레벨업/콜렉션 관리

**핵심 메서드**:
- 영웅 생성 (랜덤 스탯)
- 영웅 경험치/레벨 관리

---

### AllianceManager.py

**역할**: 연맹(길드) 시스템 전체 관리 (api_code 7001~7017)

**핵심 기능**:
- 연맹 생성/해산 (Redis → SyncWorker가 DB 동기화)
- 멤버 가입/탈퇴/추방/직위변경
- 가입 신청 승인/거절
- 경험치 기부 시스템
- 연맹 전용 연구 트리
- 공지 작성

**연맹 데이터 구조 (Redis)**:
```
alliance:{alliance_id}:info        → 연맹 기본 정보 (Hash)
alliance:{alliance_id}:members     → 멤버 목록 (Hash, user_no → JSON)
alliance:{alliance_id}:applications → 신청자 목록 (Hash)
alliance:{alliance_id}:research    → 연맹 연구 (Hash)
```

**해산 처리**: Redis에서 info 삭제 → AllianceSyncWorker가 감지 → DB에서 관련 데이터 전체 삭제

---

### NationManager.py

**역할**: 플레이어 국가 통계 관리 (전투력, 점수 등)

---

### CodexManager.py

**역할**: 게임 내 도감/백과사전 기능

---

## 매니저 간 의존 관계

```
BuildingManager
    ├─→ ResourceManager (자원 소모/환불)
    ├─→ BuffManager (건설 시간 버프)
    └─→ MissionManager (건물 완료 시 미션 체크)

ResearchManager
    ├─→ ResourceManager (자원 소모)
    └─→ BuffManager (연구 완료 시 버프 활성화)

UnitManager
    └─→ ResourceManager (자원 소모)

MissionManager
    ├─→ ResourceManager (보상 지급 - 자원)
    └─→ ItemManager (보상 지급 - 아이템)

ItemManager
    └─→ ResourceManager (아이템 효과 적용)

ShopManager
    ├─→ ResourceManager (구매 비용)
    └─→ ItemManager (아이템 지급)

LoginManager (system/)
    └─→ 모든 Manager의 {domain}_info() 호출
```
