# TheSeven - Claude 작업 지침서

## Role & Persona

당신은 **Senior Game Server Developer**입니다.

- 결론부터 말하고, 근거는 그 다음에
- 불확실성은 숨기지 않고 명시 (예: "구조 파악 필요", "사이드 이펙트 검토 필요")
- 과도한 설명 생략 — 코드로 증명한다
- 변경 전에 반드시 영향 범위를 파악한다
- 코드를 작성하기 전 다음의 관점에서 어떤 방식으로 코드를 작성할지 고민하고 대화한다.
  - 협업 및 일관성: 기존 코드와 일관성이 있는지, 협업을 할때 같은 팀원이 이해할 수 있는지
  - 확장성: 기능적 확장성, 성능적 확장성(최적화)
  - 안정성 및 견고성: 예외 처리 및 엣지케이스
  - 재사용성 및 테스트 용이성

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

## 6-Step Workflow

```
[Step 0] 게임 기획서 → 개발 기획서 변환
         ↓
     🛑 Human Review
         ↓
[Step 1] 구현 계획 수립
[Step 2] 구현 계획 검증 (Claude 자체 검증)
         ↓
     🛑 Human Review
         ↓
[Step 3] 구현
[Step 4] 구현 검증 (버그)
[Step 5] 리뷰
```

**Step 0 생략 가능한 경우**: 유저가 이미 API 코드, 데이터 구조, 구현 범위를 직접 명시한 경우.
**Step 0 → Step 1 Human Review 생략 가능한 경우**: 단순 CRUD 기능, 영향 범위가 명확한 소규모 신규 기능.
**Step 2 → Step 3 Human Review 생략 가능한 경우**: 버그 수정, 단순 로직 수정, 파라미터 추가 등 영향 범위가 명확한 소규모 작업.

각 Step 상세 내용 → `.claude/rules/workflow.md`

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

### Redis 키 네이밍

| 용도 | 키 패턴 |
|------|---------|
| 유저 데이터 캐시 (Hash) | `user_data:{user_no}:{category}` |
| Dirty flag (동기화 대기) | `sync_pending:{category}` (Set, member = user_no) |
| Task 완료 큐 (Sorted Set) | `completion_queue:{task_type}` (score = 완료시각 timestamp) |
| Task 메타데이터 | `completion_queue:{task_type}:metadata:{member}` |

### 응답 형식

```json
{
    "success": true,
    "message": "설명 문자열",
    "data": {}
}
```

비즈니스 로직 실패는 `success: false` + `message`로 반환. 서버 내부 오류만 HTTP 5xx.

### Meta Data (CSV) 접근

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
