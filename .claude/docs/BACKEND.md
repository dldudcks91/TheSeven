# BACKEND.md - 백엔드 기술 문서

> **프로젝트**: TheSeven FastAPI 서버
> **최종 수정**: 2026-03-01

> **관련 문서**: 전투/맵/행군 시스템 → [`COMBAT.md`](COMBAT.md) 참조

---

## 1. 기술 스택

| 역할 | 기술 | 비고 |
|------|------|------|
| Web Framework | FastAPI (Python async) | 비동기 처리 전용 |
| Cache / Task Queue | Redis (aioredis) | Connection Pool max 50 |
| Database | MySQL + SQLAlchemy ORM | 영속성 보장용 |
| DB Driver | pymysql | |
| Real-time | WebSocket | 작업 완료 알림 |
| Config | CSV (Pandas) | 서버 시작 시 1회 메모리 로드 |
| Client | HTML + JavaScript | iframe 기반 모듈 구조 |

---

## 2. 아키텍처 개요

```
Client (HTML/JS)
    ↓  POST /api  { user_no, api_code, data }
FastAPI (main.py)
    ↓  Depends 주입
APIManager  ←─ api_code → 해당 Game Manager 호출
    ↓
Game Manager (services/game/)
    ├─ Redis 우선 조회/갱신 (services/redis_manager/)
    └─ Redis 미스 시 DB 조회 후 캐싱 (services/db_manager/)
    ↓ (비동기, 백그라운드)
Background Workers (services/background_workers/)
    ├─ SyncWorker  : Redis dirty data → MySQL 주기적 동기화
    └─ TaskWorker  : 완료 시간 지난 게임 작업 처리 + WebSocket 알림
```

**핵심 원칙**:
- 모든 읽기/쓰기는 **Redis 경유** (Cache-Aside 패턴)
- MySQL은 영속성 보장용. 게임 로직에서 직접 조작 금지
- DB 직접 쓰기가 필요한 경우(건물 최초 생성 등)에만 DB 삽입 후 Redis 동기화

---

## 3. 디렉토리 구조

```
fastapi/
├── main.py                        # 서버 진입점, 앱 초기화, 의존성 주입
├── models.py                      # SQLAlchemy ORM 모델
├── schemas.py                     # Pydantic 스키마 (ApiRequest)
├── database.py                    # DB 연결 설정
├── meta_data/                     # 게임 밸런스 CSV (서버 시작 시 메모리 로드)
│   ├── building_info.csv
│   ├── unit_info.csv
│   ├── research_info.csv
│   ├── buff_info.csv
│   ├── item_info.csv
│   ├── shop_info.csv
│   ├── mission_info.csv
│   ├── mission_reward.csv
│   ├── alliance_level.csv
│   ├── alliance_position.csv
│   ├── alliance_research.csv
│   ├── alliance_donate.csv
│   ├── hero_info.csv
│   ├── hero_skill.csv
│   └── npc_info.csv
├── routers/
│   └── pages.py                   # HTML 페이지 라우터 (GET)
├── templates/                     # 클라이언트 HTML/JS
└── services/
    ├── system/                    # APIManager, GameDataManager, WebsocketManager
    ├── game/                      # 게임 도메인 비즈니스 로직
    ├── db_manager/                # SQLAlchemy DB 접근 레이어
    ├── redis_manager/             # Redis 캐시/큐 레이어
    └── background_workers/        # SyncWorker, TaskWorker, BattleWorker
```

---

## 4. 서버 시작 시퀀스

```python
# main.py startup_event
1. Redis Connection Pool 생성 (max 50, health_check 30s)
2. Redis 연결 테스트 (ping)
3. RedisManager 초기화 → app.state.redis_manager
4. DBManager 초기화 (SessionLocal) → app.state.db_manager
5. WebsocketManager 초기화 → app.state.websocket_manager
6. BackgroundWorkerManager 초기화 및 모든 워커 시작
7. GameDataManager.initialize() → CSV 전체 메모리 로드 (1회)
8. NpcManager.initialize() → NPC 초기 배치 (Redis map:npcs 없을 시)
9. 서버 준비 완료
```

---

## 5. API 처리 흐름

### 5.1 요청 처리 구조

```
[Client] POST /api
  body: { user_no: int, api_code: int, data: {} }
    ↓
[main.py] Depends(get_api_manager) → APIManager 주입
    ↓
APIManager.process_request(user_no, api_code, data)
    ↓
api_map에서 (ServiceClass, method_name) 조회
    ↓
ServiceClass(db_manager, redis_manager) 인스턴스 생성
service._user_no = user_no
service._data    = data
    ↓
await getattr(service, method_name)()
    ↓
반환: { "success": bool, "message": str, "data": {} }
```

### 5.2 응답 형식 (모든 /api 공통)

```json
{
    "success": true,
    "message": "설명 문자열",
    "data": {}
}
```

- 비즈니스 로직 실패(자원 부족 등): `success: false` + `message`
- 서버 내부 오류만 HTTP 5xx
- Game Manager에서 `HTTPException` 직접 raise 금지

---

## 6. api_code 라우팅 테이블

| 범위 | 도메인 | Manager |
|------|--------|---------|
| 1002 | 게임 설정 데이터 | GameDataManager |
| 1003 | 신규 유저 생성 | UserInitManager |
| 1009 | 국가 정보 | NationManager |
| 1010 | 로그인 (전체 데이터 로드) | LoginManager |
| 1011 | 자원 정보 | ResourceManager |
| 1012 | 버프 정보 | BuffManager |
| 2001~2006 | 건물 (조회/생성/업그레이드/완료/취소/전체완료) | BuildingManager |
| 3001~3004 | 연구 (조회/시작/완료/취소) | ResearchManager |
| 4001~4003 | 유닛 (조회/훈련/업그레이드) | UnitManager |
| 5001~5002 | 미션 (조회/보상수령) | MissionManager |
| 6001~6003 | 아이템 (조회/획득/사용) | ItemManager |
| 6011~6013 | 상점 (조회/새로고침/구매) | ShopManager |
| 7001~7017 | 연맹 전체 | AllianceManager |
| 8001~8002 | 영웅 (목록/지급) | HeroManager |
| 9001~9003 | 맵/NPC (내위치/맵정보/NPC목록) | MapManager |
| 9011~9013 | 행군 (목록/생성/취소) | MarchManager |
| 9021~9022 | 전투 (정보/보고서) | BattleManager |

---

## 7. Redis 패턴

### 7.1 키 네이밍 규칙

| 용도 | 키 패턴 | Redis 타입 | 예시 |
|------|---------|-----------|------|
| 유저 데이터 캐시 | `user_data:{user_no}:{category}` | Hash | `user_data:10017:building` |
| Dirty flag (동기화 대기) | `sync_pending:{category}` | Set | `sync_pending:building` (member=user_no) |
| Task 완료 큐 | `completion_queue:{task_type}` | Sorted Set | `completion_queue:unit` (score=timestamp) |
| Task 메타데이터 | `completion_queue:{task_type}:metadata:{user_no}` | String | |
| 연맹 데이터 | `alliance_data:{alliance_no}` | Hash | `alliance_data:1` |
| 국가 데이터 | `nation_data:{user_no}` | Hash | `nation_data:10017` |
| 맵 위치 | `map:positions` | Hash | `{user_no -> "x,y"}` |
| NPC 목록 | `map:npcs` | Hash | `{npc_id -> JSON}` |
| 행군 메타 | `march:metadata:{march_id}` | String (JSON) | |
| 행군 완료 큐 | `completion_queue:march` | Sorted Set | score=도착시각 |
| 귀환 완료 큐 | `completion_queue:march_return` | Sorted Set | score=귀환시각 |
| NPC 리스폰 큐 | `completion_queue:npc_respawn` | Sorted Set | score=리스폰시각 |
| 전투 상태 | `battle:{battle_id}` | Hash | 라운드/병력/상태 |
| 활성 전투 집합 | `battle:active` | Set | battle_id 집합 |

### 7.2 Cache-Aside 패턴 (읽기)

```python
# 모든 Game Manager의 데이터 조회 흐름
async def get_data(user_no):
    # 1. Redis 조회
    cached = await redis_manager.get(f"user_data:{user_no}:{category}")
    if cached:
        return cached  # 캐시 히트

    # 2. Redis miss → DB 조회
    db_data = await db_manager.get(user_no)

    # 3. Redis 캐싱
    await redis_manager.set(f"user_data:{user_no}:{category}", db_data)
    return db_data
```

### 7.3 Dirty Flag 패턴 (쓰기)

```python
# 데이터 변경 시
async def update_data(user_no, new_data):
    # 1. Redis 업데이트
    await redis_manager.set(f"user_data:{user_no}:{category}", new_data)

    # 2. Dirty flag 설정 → SyncWorker가 나중에 DB 동기화
    await redis.sadd(f"sync_pending:{category}", user_no)
```

### 7.4 원자적 자원 소모 (Lua Script)

```
ResourceRedisManager.atomic_consume(user_no, costs):
  Lua Script (원자적 실행):
    1. GET user_data:{user_no}:resource
    2. IF 모든 자원 충분:
         각 자원 DECRBY
         SADD sync_pending:resource {user_no}
         RETURN { success: true }
       ELSE:
         RETURN { success: false, shortage: {...} }
```

**목적**: 동시 요청 시에도 정확한 자원 차감 보장 (Race Condition 방지)

### 7.5 Task Queue 패턴 (완료 타이머)

```
게임 작업 시작 (훈련, 연구, 건설):
  ↓
completion_queue:{task_type} (Sorted Set)
  score  = 완료 시각 (Unix timestamp)
  member = user_no

completion_queue:{task_type}:metadata:{user_no}
  = { task_id, detail_data... }

TaskWorker 실시간 폴링 (주기: ~1초):
  ZRANGEBYSCORE completion_queue:{task_type} 0 {now}
  → 완료된 작업 처리 → WebSocket 알림
```

---

## 8. Background Workers

### 8.1 워커 목록 및 주기

| 워커 | 담당 카테고리 | 동기화 주기 |
|------|------------|-----------|
| BuildingSyncWorker | building | 10초 |
| ResearchSyncWorker | research | 10초 |
| UnitSyncWorker | unit | 30초 |
| AllianceSyncWorker | alliance | 30초 |
| ResourceSyncWorker | resource | 60초 |
| ItemSyncWorker | item | - (기본값) |
| MissionSyncWorker | mission | 120초 |
| TaskWorker | 행군도착/귀환/NPC리스폰 처리 | ~1초 (실시간) |
| BattleWorker | 전투 틱 처리 (1라운드/초) | ~1초 (실시간) |

### 8.2 Sync Worker 동작 원리

```
[SyncWorker.check() 주기 실행]
1. SMEMBERS sync_pending:{category}  → dirty 유저 목록
2. 각 user_no:
     a. HGETALL user_data:{user_no}:{category}  → Redis 데이터
     b. DB UPDATE  → MySQL 반영
     c. SREM sync_pending:{category} {user_no}  → dirty 해제
```

### 8.3 Task Worker 동작 원리

```
[TaskWorker.check() 실시간 실행]
1. ZRANGEBYSCORE completion_queue:{task_type} 0 {now}  → 완료된 작업
2. 각 user_no:
     a. 메타데이터 조회 → 어떤 작업 완료인지 파악
     b. 완료 처리 (건물 상태 변경, 유닛 ready 전환 등)
     c. MissionManager.update_progress() 호출
     d. WebsocketManager.send_personal_message() → 클라이언트 알림
     e. ZREM completion_queue:{task_type} {user_no}
```

---

## 9. DB 스키마 (models.py)

### 9.1 테이블 목록

| 테이블 | 클래스 | 설명 |
|--------|--------|------|
| stat_nation | StatNation | 플레이어 계정 + 맵 좌표 |
| building | Building | 건물 상태 |
| unit | Unit | 유닛 수량/상태 |
| research | Research | 연구 진행 상태 |
| resources | Resources | 자원 현황 |
| buff | Buff | 버프 적용 현황 |
| item | Item | 아이템 보유 현황 |
| user_mission | UserMission | 미션 진행 현황 |
| hero | Hero | 영웅 보유 현황 |
| march | March | 행군 영속 기록 |
| battle | Battle | 전투 결과 기록 |
| alliance | Alliance | 연맹 기본 정보 |
| alliance_member | AllianceMember | 연맹 멤버 |
| alliance_application | AllianceApplication | 연맹 가입 신청 |
| alliance_research | AllianceResearch | 연맹 연구 현황 |

### 9.2 주요 스키마

```python
# StatNation: 플레이어 계정 + 맵 좌표
user_no (PK), account_no, alliance_no (FK),
name, hq_lv, power, cr_dt, last_dt,
map_x, map_y  ← 맵 상 위치 (0~100)

# Building: 건물
user_no (PK), building_idx (PK), building_lv,
status (0=완료/1=건설중/2=업그레이드중),
start_time, end_time, last_dt

# Unit: 유닛
user_no (PK), unit_idx (PK),
total, ready, training, upgrading, field,
injured, wounded, healing, death,
training_end_time, cached_at

# Resources: 자원
id (PK, Auto), user_no (UNIQUE),
food, wood, stone, gold, ruby

# Alliance: 연맹
alliance_no (PK, BigInt), name (UNIQUE), leader_no,
level, exp, join_type ("free"/"approval"),
notice, notice_updated_at, created_at, updated_at

# AllianceMember: 연맹 멤버
alliance_no (PK), user_no (PK),
position (1~4), donated_exp, donated_coin, joined_at

# Hero: 영웅 보유 현황
user_no (PK), hero_idx (PK),
hero_lv, exp

# March: 행군 영속 기록 (완료/취소 포함)
march_id (PK, VARCHAR UUID), user_no,
status (marching/battling/returning/completed/cancelled),
target_type (user/npc), target_user_no, npc_id,
from_x, from_y, to_x, to_y,
departure_time, arrival_time, return_time,
units (JSON), hero_idx, battle_id

# Battle: 전투 결과 기록
battle_id (PK, VARCHAR UUID), march_id,
attacker_no, defender_no, npc_id,
attacker_win, rounds,
attacker_losses (JSON), defender_losses (JSON),
loot (JSON), hero_exp, created_at

# AllianceResearch: 연맹 연구
alliance_no (PK), research_idx (PK),
level, current_exp, is_active,
activated_by, activated_at, completed_at
```

---

## 10. GameDataManager (CSV 메타데이터)

### 10.1 로드 구조

서버 시작 시 `GameDataManager.initialize()` 1회 실행. 이후 런타임에는 메모리 접근만 함.

```python
GameDataManager.REQUIRE_CONFIGS = {
    'building':            { idx: { lv: { cost, time, ... } } },
    'research':            { idx: { lv: { cost, time, buff_idx, ... } } },
    'unit':                { idx: { tier, stats, ... } },
    'buff':                { idx: { type, effect, ... } },
    'item':                { idx: { category, value, ... } },
    'mission':             { idx: { category, target, value, ... } },
    'mission_index':       { category: [mission_idx, ...] },
    'shop':                { idx: { weight } },
    'alliance_level':      { level: { max_members, required_exp } },
    'alliance_position':   { position: { permissions... } },
    'alliance_research':   { idx: { lv: { required_exp, buff_idx, ... } } },
    'alliance_donate':     { resource_type: { exp_ratio, coin_ratio } },
    'hero':                { idx: { korean_name, tier, base_atk, base_def, ... } },
    'hero_skill':          { idx: { skill_type, effect, ... } },
    'npc':                 { idx: { korean_name, tier, exp_reward, units, ... } },
}
```

### 10.2 올바른 접근 방법

```python
# ✅ 올바른 방법
data = GameDataManager.REQUIRE_CONFIGS.get('building', {}).get(building_idx, {})

# ❌ 금지 — 런타임 CSV 직접 읽기
df = pd.read_csv("meta_data/building_info.csv")
```

---

## 11. 레이어별 책임 및 금지사항

| 레이어 | 책임 | 금지사항 |
|--------|------|---------|
| `services/system/` | API 라우팅, 로그인, 게임 데이터 로드 | 게임 비즈니스 로직 |
| `services/game/` | 게임 규칙, 상태 검증, 비즈니스 로직 | DB 직접 쓰기 |
| `services/redis_manager/` | Redis 읽기/쓰기, 키 관리 | 비즈니스 결정 |
| `services/db_manager/` | SQLAlchemy 쿼리 실행 | 비즈니스 로직 |
| `services/background_workers/` | 주기적 동기화, 완료 이벤트 처리 | 동기 API 응답 처리 |

---

## 12. 신규 기능 개발 가이드

### 12.1 새 API 추가 절차

1. `services/game/{domain}_manager.py`에 메서드 구현
   ```python
   async def new_feature(self) -> dict:
       # 비즈니스 로직
       return {"success": True, "message": "...", "data": {...}}
   ```

2. `services/system/APIManager.py`의 `api_map`에 등록
   ```python
   api_map = {
       ...
       9001: (NewManager, "new_feature"),
   }
   ```

3. `API.md`에 명세 추가

4. Redis 접근 필요 시 → `services/redis_manager/` 메서드 추가

5. DB 접근 필요 시 → `services/db_manager/` 메서드 추가

### 12.2 신규 Game Manager 추가 패턴

```python
# services/game/new_manager.py
class NewManager:
    def __init__(self, db_manager, redis_manager):
        self._db_manager    = db_manager
        self._redis_manager = redis_manager
        self._user_no = None
        self._data    = None

    async def feature_method(self) -> dict:
        ...
        return {"success": True, "message": "...", "data": {}}
```

### 12.3 자가 검증 체크리스트

**레이어 준수**
- [ ] Game Manager가 DB에 직접 쓰지 않는다 (Redis 경유)
- [ ] DB 직접 삽입이 필요한 경우, Redis에도 동기화했다
- [ ] `async/await` 누락 없음 (aioredis 호출 포함)

**Redis 체크**
- [ ] 키 네이밍이 기존 규칙(`user_data:{user_no}:{category}`)을 따른다
- [ ] 쓰기 작업에 dirty flag(`sync_pending:{category}`) 설정됨
- [ ] Task Queue 등록이 필요한 경우 처리됨

**API 체크**
- [ ] 응답 형식이 `{ success, message, data }` 구조를 따른다
- [ ] `api_map`에 등록됐다
- [ ] `API.md`에 명세 추가됐다

**에러 처리**
- [ ] 자원 부족/조건 미충족은 `success: false`로 반환
- [ ] Game Manager에서 `HTTPException` 직접 raise 금지

---

## 13. 성능 고려사항

### 13.1 Redis Connection Pool

```python
ConnectionPool(
    max_connections=50,       # 최대 50개 동시 연결
    health_check_interval=30, # 30초마다 헬스체크
    retry_on_timeout=True     # 타임아웃 시 재시도
)
```

### 13.2 로그인 병렬 로드

```python
# LoginManager: asyncio.gather()로 병렬 처리
# Phase 1 (독립 데이터 동시 로드):
await asyncio.gather(
    nation_manager.nation_info(),
    building_manager.building_info(),
    unit_manager.unit_info(),
    research_manager.research_info(),
    resource_manager.resource_info(),
    item_manager.item_info(),
    shop_manager.shop_info(),
)
# Phase 2 (Phase 1 결과 의존):
await asyncio.gather(
    buff_manager.buff_info(),
    mission_manager.mission_info(),
)
```

### 13.3 SyncWorker 주기 전략

| 주기 | 카테고리 | 이유 |
|------|---------|------|
| 10초 | building, research | 변경 빈도 낮음, 유실 영향 높음 |
| 30초 | unit, alliance | 변경 빈도 중간 |
| 60초 | resource | 변경 빈도 높음, 유실 영향 상대적 낮음 |
| 120초 | mission | 변경 빈도 매우 낮음 |

---

## 14. 실행 방법

```bash
# 서버 시작 (개발)
cd fastapi
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# 서버 시작 (포트 변경 시)
uvicorn main:app --host 0.0.0.0 --port {PORT}
```

> **주의**: Python 코드 변경 후에는 서버를 반드시 재시작해야 반영됨 (`--reload` 없이 실행 시)

---

## 15. 공통 장애 패턴 및 대응

| 상황 | 대응 |
|------|------|
| Redis에서 유저 데이터 없음 | DB 로드 후 Redis 캐싱 → 재조회 |
| DB 스키마와 models.py 불일치 | models.py 기준으로 보고 후 수정 방향 제안 |
| Background Worker 예외 | 로깅 후 다음 사이클로 진행 (서버 중단 금지) |
| Redis 경합 (동시성) | 원자적 연산(`MULTI/EXEC`, Lua Script) 사용 |
| api_code 미등록 요청 | `success: false, message: "Unknown api_code"` |
| 게임 CSV 데이터 변경 | 서버 재시작 필요 (런타임 reload 불가) |
