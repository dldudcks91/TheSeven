# TheSeven - 4X Game Server

## 프로젝트 개요

멀티플레이어 4X 전략 게임의 백엔드 서버. FastAPI 기반 비동기 서버로, Redis를 주 데이터 저장소(Cache-Aside)로 사용하고 MySQL을 영속 저장소로 사용하는 2-Tier 캐시 구조를 채택함.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| Web Framework | FastAPI (Python async) |
| Cache / Task Queue | Redis (aioredis, Connection Pool max 50) |
| Database | MySQL + SQLAlchemy ORM (pymysql) |
| Real-time | WebSocket |
| Config | CSV (Pandas로 서버 시작 시 1회 메모리 로드) |
| Client | HTML + JavaScript (iframe 기반 모듈 구조) |

---

## 아키텍처 레이어

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

**핵심 원칙**: 모든 읽기/쓰기는 Redis를 통한다. MySQL은 영속성 보장용이며 직접 조작하지 않는다. DB 직접 쓰기가 필요한 경우(건물 최초 생성 등)에만 DB에 직접 삽입 후 Redis에도 동기화.

---

## 디렉토리 구조

```
fastapi/
├── main.py                        # 서버 진입점, 앱 초기화, 라우터 등록
├── models.py                      # SQLAlchemy ORM 모델 (MySQL 테이블 정의)
├── schemas.py                     # Pydantic 스키마 (ApiRequest 등)
├── database.py                    # DB 연결 설정 (SessionLocal, engine)
├── meta_data/                     # 게임 밸런스 CSV 파일 (서버 시작 시 메모리 로드)
│   ├── building_info.csv
│   ├── unit_info.csv
│   ├── research_info.csv
│   ├── buff_info.csv
│   ├── item_info.csv
│   ├── shop_info.csv
│   ├── mission_info.csv
│   └── mission_reward.csv
├── routers/
│   ├── pages.py                   # HTML 템플릿 라우터
│   └── game_data.py               # 레거시 REST 라우터 (현재는 /api 단일 엔드포인트 사용)
├── templates/                     # 클라이언트 HTML/JS
│   ├── main.html                  # 메인 대시보드 (탭 + iframe 구조)
│   └── *.html                     # 도메인별 UI (building, unit, research 등)
└── services/
    ├── system/                    # 시스템 레이어 (API 라우팅, 로그인, 데이터 로드)
    ├── game/                      # 게임 도메인 레이어 (비즈니스 로직)
    ├── db_manager/                # DB 접근 레이어 (SQLAlchemy)
    ├── redis_manager/             # Redis 캐시/큐 레이어 (aioredis)
    └── background_workers/        # 비동기 백그라운드 워커
```

---

## 서버 시작 시퀀스 (main.py startup_event)

1. Redis Connection Pool 생성 (max 50, health_check 30s)
2. Redis 연결 테스트 (ping)
3. `RedisManager` 초기화 → `app.state.redis_manager` 저장
4. `DBManager` 초기화 (SessionLocal 생성) → `app.state.db_manager` 저장
5. `WebsocketManager` 초기화 → `app.state.websocket_manager` 저장
6. `BackgroundWorkerManager` 초기화 및 전체 워커 시작
7. `GameDataManager.initialize()` → CSV 전체 메모리 로드 (1회)
8. 서버 준비 완료

---

## 단일 API 엔드포인트 구조

모든 게임 API는 `POST /api` 하나로 처리.

**Request 형식:**
```json
{
    "user_no": 1,
    "api_code": 2003,
    "data": {"building_idx": 101}
}
```

**Response 형식 (공통):**
```json
{
    "success": true,
    "message": "...",
    "data": {}
}
```

`APIManager`가 `api_code`를 보고 해당 `(ServiceClass, method)` 튜플을 찾아 인스턴스 생성 후 호출. 상세 내용은 `API.md` 참고.

---

## WebSocket 엔드포인트

```
WS /ws/{user_no}
```

- 연결 시 `{type: 'connected', user_no}` 전송
- ping/pong, heartbeat 지원
- `BackgroundWorkerManager`의 `TaskWorker`가 게임 작업 완료 시 해당 유저에게 push

---

## 헬스체크 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /health` | Redis, GameData, WebSocket, Worker 상태 |
| `GET /pool-status` | Redis/DB 커넥션 풀 상세 통계 |

---

## MySQL 테이블 구조 요약

```
StatNation               # 플레이어 계정 (루트 엔티티)
├── Building             # 건물 (building_idx, building_lv, status, start_time, end_time)
├── Unit                 # 유닛 (unit_idx, 훈련 수량, status)
├── Research             # 연구 (research_idx, research_lv, status)
├── Resources            # 자원 (food, wood, stone, gold, ruby)
├── Buff                 # 버프 (buff_idx, start_time, end_time)
├── Item                 # 아이템 인벤토리 (item_idx, quantity)
├── UserMission          # 미션 진행 (mission_idx, is_completed, is_claimed)
├── Hero                 # 영웅 (hero_lv, exp)
└── AllianceMember       # 연맹 소속

Alliance                 # 연맹
├── AllianceMember       # 연맹 멤버 (role 포함)
├── AllianceApplication  # 가입 신청
└── AllianceResearch     # 연맹 연구 트리
```

---

## Redis 키 네이밍 규칙

| 용도 | 키 패턴 |
|------|---------|
| 유저 데이터 캐시 (Hash) | `user_data:{user_no}:{category}` |
| Dirty flag (동기화 대기) | `sync_pending:{category}` (Set, member = user_no) |
| Task 완료 큐 (Sorted Set) | `completion_queue:{task_type}` (score = 완료시각 timestamp) |
| Task 메타데이터 | `completion_queue:{task_type}:metadata:{member}` |

---

## 게임 시스템 목록

| 시스템 | API 코드 | 담당 Manager |
|--------|----------|--------------|
| 자원 (food/wood/stone/gold/ruby) | 1011 | ResourceManager |
| 버프 | 1012 | BuffManager |
| 건물 | 2xxx | BuildingManager |
| 연구 (테크트리) | 3xxx | ResearchManager |
| 유닛 | 4xxx | UnitManager |
| 미션/퀘스트 | 5xxx | MissionManager |
| 아이템 | 60xx | ItemManager |
| 상점 | 601x | ShopManager |
| 영웅 | - | HeroManager |
| 연맹 (길드) | 7xxx | AllianceManager |
| 국가 정보 | - | NationManager |

---

## 각 레이어 상세 문서

- [services/system/README.md](services/system/README.md) - 시스템 레이어
- [services/game/README.md](services/game/README.md) - 게임 도메인 레이어
- [services/db_manager/README.md](services/db_manager/README.md) - DB 접근 레이어
- [services/redis_manager/README.md](services/redis_manager/README.md) - Redis 레이어
- [services/background_workers/README.md](services/background_workers/README.md) - 백그라운드 워커
- [API.md](API.md) - 전체 API 명세
