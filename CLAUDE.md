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

## 4-Step Workflow
```
[Step 1] 구현 계획 수립
[Step 2] 구현 계획 검증 (Claude 자체 검증)
         ↓
     🛑 Human Review
         ↓
[Step 3] 구현
[Step 4] 구현 검증 (버그)
[Step 5] 리뷰
```

**Human Review 생략 가능한 경우**: 버그 수정, 단순 로직 수정, 파라미터 추가 등 영향 범위가 명확한 소규모 작업.

---


### Step 1: 구현 계획 수립

#### 1. 영향 범위 파악
작업 시작 전 반드시 확인:
- 어느 레이어가 영향 받는가 (system / game / db_manager / redis_manager / worker)
- 어느 api_code 범위에 해당하는가
- Redis 키 구조 변경이 필요한가
- DB 스키마(models.py) 변경이 필요한가
- Background Worker 로직 변경이 필요한가

#### 2. 계획 수립 관점
영향 범위 파악 후 아래 3가지 관점에서 계획을 수립한다.

[아키텍처 관점]
- 레이어 책임 위반이 없는가
- 기존 패턴과 일관성이 있는가
- 기존 컴포넌트 확장으로 가능한가, 새 컴포넌트가 필요한가

[동시성/성능 관점]
- Redis 경합이 발생할 수 있는 지점이 있는가
- 원자적 연산이 필요한 구간이 있는가 (MULTI/EXEC, Lua 스크립트)
- 다수 유저 동시 접근 시 병목이 예상되는가

[영향 범위 관점]
- 변경이 다른 Manager/Worker에 연쇄적으로 미치는가
- 기존 Redis 키를 사용하는 다른 로직에 영향이 없는가
- api_code 체계에서 범위 충돌이 없는가

#### 3. 계획서 산출물
계획 수립 후 아래 형식으로 계획서를 작성한다:
- 영향받는 파일 목록
- 변경 함수 시그니처 (pseudo-code 수준)
- Redis 키 변경사항
- DB 스키마 변경사항 (있는 경우)
- 예상 사이드이펙트 목록
- api_code 번호 (신규 API인 경우)
- Background Worker 연동 여부

---
### Step 2: 구현 계획 검증

Step 1의 계획서를 아래 관점으로 검증한다.
모든 관점을 검토하되, 우선순위에 따라 검토 깊이를 조정한다.
1순위 항목에서 문제 발견 시 즉시 Step 1으로 되돌아간다.

---

#### 고정 우선순위 관점

**1순위 - 데이터 정합성**
- Redis → DB 동기화 누락 가능성이 있는가
- dirty flag 누락으로 인한 데이터 유실 가능성이 있는가
- 부분 실패 시 Redis와 DB 상태가 불일치할 수 있는가
- 트랜잭션 범위가 적절한가

**2순위 - 아키텍처**
- 레이어 책임 위반이 없는가 (Game Manager DB 직접 쓰기 등)
- 기존 패턴과 일관성이 있는가
- 기존 컴포넌트 확장으로 가능한데 새 컴포넌트를 만들려는 건 아닌가

**3순위 - 장애 복구/안정성**
- Worker 예외 발생 시 서버 중단 없이 다음 사이클로 진행되는가
- Redis 미스 시 DB 폴백 로직이 있는가
- 예외를 Game Manager에서 직접 raise하는 계획은 없는가

**4순위 - 보안**
- 입력값 검증이 계획에 포함되어 있는가
- 다른 유저 데이터에 접근 가능한 경로가 없는가

---

#### 동적 우선순위 관점

**동시성/성능**: 아래 기준으로 검토 깊이를 스스로 판단한다.

| 해당 시 순위 올림 (1~2순위 수준) | 해당 시 순위 내림 (4순위 이하) |
|-------------------------------|---------------------------|
| WebSocket 실시간 통신 | 단순 CRUD |
| 전투/행군 등 다수 유저 동시 이벤트 | 건물 완료 등 단일 유저 이벤트 |
| 대용량 데이터 처리 | 저빈도 호출 API |

순위 올림 시 아래 항목을 반드시 검토:
- Redis 경합이 발생할 수 있는 지점이 있는가
- 원자적 연산이 필요한 구간이 있는가 (MULTI/EXEC, Lua 스크립트)
- 다수 유저 동시 접근 시 병목이 예상되는가
- Connection Pool (max 50) 한계에 근접하는 시나리오가 있는가

---

#### 빠꾸 기준
아래 중 하나라도 해당하면 Step 1으로 되돌아간다:
- 1순위(데이터 정합성) 항목에서 문제 발견
- 레이어 책임 위반이 계획에 포함된 경우
- 동시성/성능이 순위 올림 대상인데 원자적 연산 계획이 없는 경우
- 예상 사이드이펙트가 계획서에 누락된 경우

---

### Step 3: 구현

Step 1 계획서를 기준으로 구현한다.

#### 구현 원칙
- 계획서에 정의된 함수 시그니처, 레이어 구조, Redis 키를 그대로 따른다
- 계획서에 없는 로직을 임의로 추가하지 않는다
- 구현 중 계획서와 달라지는 부분이 생기면 그 이유와 함께 명시한다

#### 구현 체크리스트
**레이어**
- [ ] Game Manager가 DB에 직접 쓰지 않는다 (Redis 경유)
- [ ] DB 직접 삽입이 필요한 경우 Redis에도 동기화했다
- [ ] async/await 누락 없음 (aioredis 호출 포함)

**Redis**
- [ ] 키 네이밍이 도메인별 규칙을 따른다
      (유저: user_data:{user_no}:{category} / 그 외 도메인은 Coding Conventions 참고)
- [ ] dirty flag(sync_pending:{category}) 설정이 필요한 쓰기 작업에 적용됨
- [ ] Task Queue 등록이 필요한 경우(completion_queue:{task_type}) 처리함

**API**
- [ ] 응답 형식이 공통 구조(success, message, data)를 따른다
- [ ] api_code를 APIManager 라우팅 테이블에 등록했다
- [ ] API.md에 명세를 추가/수정했다

**에러 처리**
- [ ] 존재하지 않는 데이터 접근 시 명확한 실패 메시지 반환
- [ ] 비즈니스 로직 실패를 success: false로 반환
- [ ] Game Manager에서 HTTPException 직접 raise 없음

#### 계획 변경 발생 시
계획서와 달라진 부분을 아래 형식으로 기록한다:
- 변경 위치 (파일명 / 함수명)
- 변경 내용
- 변경 이유

변경 범위가 크거나 아키텍처에 영향을 주는 경우 Step 1부터 다시 시작한다.

---
### Step 4: 구현 검증 (버그)

작업 성격에 따라 검증 수준을 나눈다.

---

#### 고도 개발 판단 기준
아래 중 하나라도 해당하면 고도 개발로 분류한다:
- 전투/행군 관련 로직 변경
- Worker 로직 변경
- Redis ↔ DB 동기화 로직 변경
- 다수 유저가 동시에 영향받는 기능

---

#### 일반 개발 검증

**1. Step 2 관점 재검토**
계획 검증 시 사용한 관점으로 실제 구현된 코드를 재확인한다.
계획서와 구현 결과가 일치하는지 확인하고,
Step 3에서 명시한 계획 변경사항이 새로운 문제를 만들지 않는지 확인한다.

**2. 엣지케이스 검증**
아래 시나리오를 기준으로 코드 실행 흐름을 추적한다.

[데이터 경계]
- 자원/수치가 0이거나 최대치일 때
- Redis에 데이터 없음 (최초 접근)
- Redis에는 있으나 DB에 없는 상태

[동시성]
- 같은 유저가 동일 요청을 동시에 두 번 보낼 때
- Worker 처리 중 유저가 관련 액션을 취할 때
- Redis 키 만료 타이밍과 쓰기 작업이 겹칠 때

[실패 흐름]
- DB 조회 실패 시 폴백이 동작하는가
- 부분 성공 시 (Redis 저장 성공, DB 동기화 실패) 정합성이 깨지지 않는가
- Worker 예외 발생 시 다음 사이클에 영향이 없는가

**3. API 실제 송수신 테스트**
- 구현된 API를 실제로 호출하여 요청/응답 형식 확인
- 정상 흐름 및 실패 흐름 (success: false) 응답 확인

---

#### 고도 개발 검증
일반 개발 검증 전체 + 아래 추가 검증을 진행한다.

**4. 정합성 테스트**
- Redis → DB 동기화 누락 없이 완료되는지 확인
- dirty flag 처리 후 실제 DB 반영 여부 확인
- 부분 실패 시 Redis ↔ DB 불일치 상태 발생 여부 확인
- 전투 관련 변경 시: 전투 전/후 병력 수 무결성 검증
  (전투 중 지원군 합류, 버프 적용, Worker 업데이트 타이밍 간섭 포함)

**5. 부하 테스트**
- 다수 유저 동시 접속 시 응답 속도 확인
- Connection Pool (max 50) 한계 도달 시점 확인
- WebSocket 실시간 처리 한계 확인

---

#### 버그 발견 시 처리

| 심각도 | 기준 | 처리 |
|--------|------|------|
| 즉시 수정 | 데이터 정합성 파괴, 서버 크래시 가능성, 다른 유저 데이터 접근 | Step 3으로 돌아가 수정 후 재검증 |
| 로그 기록 | 엣지케이스 미처리, 성능 개선 여지, 경고성 이슈 | Step 5 버그 로그에 기록 후 진행 |

--- 


### Step 5: 리뷰

구현 완료 후 아래 순서로 정리한다.

---

#### 1. 작업 완료 요약 (버전관리.md)
아래 항목을 버전관리.md에 한 줄 요약으로 추가한다:
- 작업 내용
- 변경된 파일 목록
- Step 3에서 명시한 계획 변경사항 (있는 경우)

---

#### 2. 버그 로그 (BUG_LOG.md)
Step 4에서 발견된 버그와 이슈를 아래 형식으로 기록한다.
```markdown
## [날짜] 작업명

### 즉시 수정한 버그
- 발생 위치: (파일명 / 함수명)
- 원인:
- 해결:

### 미해결 이슈
- 발생 위치: (파일명 / 함수명)
- 원인:
- 영향 범위:
- 해결 방향:

### 알려진 한계/주의사항
- 내용:
```

발견된 버그/이슈가 없는 경우 "이슈 없음"으로 기록한다.
버그가 누적되면 Common Failure Patterns 섹션을 주기적으로 업데이트한다.

---

#### 3. 문서 업데이트 확인
Step 3 체크리스트의 API.md 업데이트가 완료되었는지 최종 확인한다.
미완료 항목이 있으면 즉시 처리 후 완료 표시한다.

---

#### 4. 미완료 항목 명시
작업 중 완료하지 못한 항목이 있으면 명시적으로 남긴다.
다음 세션 시작 시 Session Recovery에서 이 항목을 우선 확인한다.


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
