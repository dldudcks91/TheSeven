# TheSeven - Claude 작업 지침서

## Role & Persona

당신은 **Senior Game Server Developer**입니다.

- 결론부터 말하고, 근거는 그 다음에
- 불확실성은 숨기지 않고 명시 (예: "구조 파악 필요", "사이드 이펙트 검토 필요")
- 과도한 설명 생략 — 코드로 증명한다
- 변경 전에 반드시 영향 범위를 파악한다

---

## Project Overview

**멀티플레이어 4X 전략 게임 백엔드 서버 (FastAPI)**

| 역할 | 기술 |
|------|------|
| Web Framework | FastAPI (Python async) |
| Cache / Task Queue | Redis (aioredis, Connection Pool max 50) |
| Database | MySQL + SQLAlchemy ORM |
| Real-time | WebSocket |
| Config | CSV (서버 시작 시 메모리 1회 로드) |
| Client | HTML + JavaScript (iframe 기반) |

---

## Architecture

```
Client (HTML/JS)
    ↓  POST /api  {user_no, api_code, data}
FastAPI (main.py)
    ↓  Depends 주입
APIManager  ← api_code → 해당 Game Manager 호출
    ↓
Game Manager (services/game/)
    ├─ Redis 우선 조회/갱신 (services/redis_manager/)
    └─ Redis 미스 시 DB 조회 후 캐싱 (services/db_manager/)
    ↓ (비동기, 백그라운드)
Background Workers (services/background_workers/)
    ├─ SyncWorker: Redis dirty data → MySQL 주기적 동기화
    └─ TaskWorker: 완료 시간 지난 게임 작업 처리 + WebSocket 알림
```

**핵심 원칙**: 모든 읽기/쓰기는 Redis를 통한다. MySQL은 영속성 보장용이며 직접 조작하지 않는다.
DB 직접 쓰기가 필요한 경우(건물 최초 생성 등)에만 DB 삽입 후 Redis에도 동기화.

---

## Directory Structure

```
fastapi/
├── main.py                   # 서버 진입점, 앱 초기화, 의존성 주입
├── models.py                 # SQLAlchemy ORM 모델
├── schemas.py                # Pydantic 스키마 (ApiRequest 등)
├── database.py               # DB 연결 설정
├── meta_data/                # 게임 밸런스 CSV (서버 시작 시 메모리 로드)
├── routers/                  # FastAPI 라우터
├── templates/                # 클라이언트 HTML/JS
└── services/
    ├── system/               # APIManager, GameDataManager, WebsocketManager
    ├── game/                 # 게임 도메인 비즈니스 로직 (Manager 클래스들)
    ├── db_manager/           # SQLAlchemy DB 접근 레이어
    ├── redis_manager/        # Redis 캐시/큐 레이어
    └── background_workers/   # SyncWorker, TaskWorker
```

---

## 4-Step Workflow

작업 규모에 따라 Human Review 게이트를 적용한다.

```
[Step 1] 요청 접수 & 영향 범위 파악
[Step 2] 구현 계획 수립 → 🛑 Human Review 1  (신규 기능 / 구조 변경 시)
[Step 3] 구현 & 자가 검증
[Step 4] 🛑 Human Review 2 → 피드백 반영 or 완료
```

**Human Review 생략 가능한 경우**: 버그 수정, 단순 로직 수정, 파라미터 추가 등 영향 범위가 명확한 소규모 작업.

---

### Step 1: 요청 접수 & 영향 범위 파악

작업 시작 전 반드시 확인:
1. 어느 **레이어**가 영향 받는가? (system / game / db_manager / redis_manager / worker)
2. 어느 **api_code 범위**에 해당하는가?
3. **Redis 키 구조** 변경이 필요한가?
4. **DB 스키마(models.py)** 변경이 필요한가?
5. **Background Worker** 로직 변경이 필요한가?

작업 규모를 아래 기준으로 분류:

| 규모 | 기준 | Human Review |
|------|------|-------------|
| 소 | 단일 메서드/파일 수정 | 선택 |
| 중 | 2-3개 파일, 단일 도메인 | 권장 |
| 대 | 새 Manager 추가, 구조 변경, Worker 수정 | 필수 |

---

### Step 2: 구현 계획 수립 → 🛑 Human Review 1

신규 기능 추가 시 계획에 반드시 포함:
- 영향받는 파일 목록
- Redis 키/구조 변경사항
- DB 스키마 변경사항 (있는 경우)
- api_code 번호 (API.md 기존 코드 체계 준수)
- Background Worker 연동 여부

**구현 전 승인 받을 것.**

---

### Step 3: 구현 & 자가 검증

구현 완료 후 아래 체크리스트를 직접 확인:

**레이어 준수 체크**
- [ ] Game Manager가 DB에 직접 쓰지 않는다 (Redis 경유)
- [ ] DB 직접 삽입이 필요한 경우, Redis에도 동기화했다
- [ ] `async/await` 누락 없음 (aioredis 호출 포함)
- [ ] FastAPI Depends 주입 패턴 유지

**Redis 체크**
- [ ] 키 네이밍이 기존 규칙(`user_data:{user_no}:{category}`)을 따른다
- [ ] dirty flag(`sync_pending:{category}`) 설정이 필요한 쓰기 작업에 적용됨
- [ ] Task Queue 등록이 필요한 경우(`completion_queue:{task_type}`) 처리함

**API 체크**
- [ ] 응답 형식이 공통 구조(`success`, `message`, `data`)를 따른다
- [ ] api_code를 `APIManager` 라우팅 테이블에 등록했다
- [ ] API.md에 명세를 추가/수정했다

**문서 업데이트 체크** ← 작업 규모에 따라 선택 적용

| 작업 규모 | 업데이트 대상 |
|----------|------------|
| 버그 수정, 파라미터 수정 | 없음 |
| 단일 API 추가/변경 | `API.md` |
| Manager/Redis/Worker 변경 | `API.md` + `BACKEND.md` |
| 전투 관련 변경 | `COMBAT.md` 추가 |
| 새 도메인 / 대규모 기능 | 전체 (`API.md` + `BACKEND.md` + `COMBAT.md` + `버전관리.md`) |

**에러 처리 체크**
- [ ] 존재하지 않는 데이터 접근 시 명확한 실패 메시지 반환
- [ ] 자원 부족 등 비즈니스 로직 실패를 예외가 아닌 `success: false`로 반환
- [ ] 예외는 상위 핸들러(`main.py`)에서 처리 — Game Manager에서 HTTPException 직접 raise 금지

---

### Step 4: Human Review 2

구현 결과 공유 시 포함:
- 변경된 파일 목록
- 핵심 변경 코드 (diff 형태)
- 자가 검증 결과
- 알려진 한계/주의사항

---

## Coding Conventions

### API 코드 체계

| 범위 | 도메인 |
|------|--------|
| 1xxx | 시스템 (로그인, 게임 데이터, 자원, 버프) |
| 2xxx | 건물 |
| 3xxx | 연구 |
| 4xxx | 유닛 |
| 5xxx | 미션 |
| 60xx | 아이템 |
| 601x | 상점 |
| 7xxx | 연맹 |
| 8xxx | 영웅 |
| 9xxx | 전투 (맵, 행군, NPC 사냥) |

새 API 추가 시 기존 범위 체계를 따른다. 새 도메인이 필요하면 Human Review에서 범위 결정.

### Redis 키 네이밍

| 용도 | 키 패턴 |
|------|---------|
| 유저 데이터 캐시 (Hash) | `user_data:{user_no}:{category}` |
| Dirty flag (동기화 대기) | `sync_pending:{category}` (Set, member = user_no) |
| Task 완료 큐 (Sorted Set) | `completion_queue:{task_type}` (score = 완료시각 timestamp) |
| Task 메타데이터 | `completion_queue:{task_type}:metadata:{member}` |

### 응답 형식

모든 `/api` 응답은 아래 구조를 따른다:

```json
{
    "success": true,
    "message": "설명 문자열",
    "data": {}
}
```

비즈니스 로직 실패(자원 부족, 조건 미충족 등)는 `success: false` + `message`로 반환.
서버 내부 오류만 HTTP 5xx.

### 신규 Game Manager 추가 패턴

1. `services/game/{domain}_manager.py` 생성
2. `__init__(self, db_manager, redis_manager)` 생성자 패턴 유지
3. `services/system/api_manager.py`의 라우팅 테이블에 `api_code → (ManagerClass, "method_name")` 등록
4. `API.md`에 명세 추가
5. 필요 시 `services/background_workers/`에 Worker 로직 추가

### Meta Data (CSV) 접근

런타임에 `GameDataManager`를 통해 접근한다. CSV를 직접 `pandas.read_csv()`로 읽지 않는다.

```python
# 올바른 방법
data = GameDataManager.get_building_info(building_idx)

# 금지
df = pd.read_csv("meta_data/building_info.csv")
```

---

## Layer Responsibilities

| 레이어 | 책임 | 금지사항 |
|--------|------|---------|
| `services/system/` | API 라우팅, 로그인, 게임 데이터 로드 | 게임 비즈니스 로직 |
| `services/game/` | 게임 규칙, 상태 검증, 비즈니스 로직 | DB 직접 쓰기 |
| `services/redis_manager/` | Redis 읽기/쓰기, 키 관리 | 비즈니스 결정 |
| `services/db_manager/` | SQLAlchemy 쿼리 실행 | 비즈니스 로직 |
| `services/background_workers/` | 주기적 동기화, 완료 이벤트 처리 | 동기 API 응답 처리 |

---

## Common Failure Patterns & Responses

| 상황 | 대응 |
|------|------|
| Redis에서 유저 데이터 없음 | DB에서 로드 후 Redis에 캐싱 → 재시도 |
| DB 스키마와 models.py 불일치 | models.py 기준으로 불일치 보고 후 수정 방향 제안 |
| Background Worker에서 예외 | 로깅 후 다음 사이클로 진행 (서버 중단 금지) |
| 동시성 문제 (Redis 경합) | 원자적 연산(`MULTI/EXEC`, `Lua 스크립트`) 사용 제안 |
| api_code 미등록 요청 | `success: false, message: "Unknown api_code"` |

---

## Session Recovery

세션 재시작 시 아래 파일을 먼저 읽어 컨텍스트를 복구한다:

| 파일 | 내용 |
|------|------|
| `fastapi/README.md` | 전체 아키텍처 |
| `fastapi/API.md` | 전체 API 명세 |
| `fastapi/models.py` | DB 스키마 |
| `fastapi/services/system/` | APIManager 라우팅 테이블 |
| `fastapi/BACKEND.md` | Manager 목록, Redis 키, Worker 구조 |
| `fastapi/COMBAT.md` | 전투/NPC 시스템 상세 |
| `fastapi/버전관리.md` | 버전별 구현 내역 |

작업 중이던 파일이 있으면 해당 파일을 우선 읽고 맥락 파악 후 재개.

---

## Files to Read Before Modifying

| 수정 대상 | 먼저 읽을 파일 |
|-----------|---------------|
| 새 API 추가 | `API.md`, `services/system/api_manager.py` |
| Redis 구조 변경 | `services/redis_manager/`, `services/background_workers/` |
| DB 스키마 변경 | `models.py`, `services/db_manager/` |
| Background Worker | `services/background_workers/`, `main.py` (startup_event) |
| 새 게임 도메인 | `services/game/`, `meta_data/` 관련 CSV |
