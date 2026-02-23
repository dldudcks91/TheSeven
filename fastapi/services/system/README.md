# services/system - 시스템 레이어

## 역할

게임 도메인 로직과 무관한 인프라/진입점 담당 레이어. API 라우팅, 로그인 오케스트레이션, 게임 데이터 로드, 유저 초기화, WebSocket 연결 관리를 처리.

---

## 파일 목록

### APIManager.py

**역할**: 모든 게임 API 요청의 진입점 (Facade + Router 패턴)

**구현 방식**:
- `api_map` 딕셔너리에 `api_code → (ServiceClass, method)` 튜플 매핑 저장
- `process_request(user_no, api_code, data)` 호출 시:
  1. api_map에서 해당 클래스/메서드 조회
  2. `ServiceClass(db_manager, redis_manager)` 인스턴스 생성
  3. `instance.user_no = user_no`, `instance.data = data` 세팅
  4. `await method(instance)` 실행 후 결과 반환
- `GameDataManager`는 싱글톤(클래스 메서드)이므로 인스턴스 생성 없이 직접 호출
- `main.py`에서 FastAPI Depends로 주입받아 사용

**의존성**: `DBManager`, `RedisManager` (생성자 주입)

---

### LoginManager.py

**역할**: 로그인 시 필요한 모든 데이터 로드 오케스트레이터 (api_code: 1010)

**구현 방식**:
- Phase 1 병렬 로드: `building, unit, research, resource, item, shop` → `asyncio.gather()`
- Phase 2 병렬 로드 (Phase1 의존): `buff, mission` → `asyncio.gather()`
- 진행 중 작업 Redis Queue 재등록: `unit_tasks, research_tasks` 병렬 등록
  - 서버 재시작 시 진행 중이던 작업의 완료 시각을 Task Queue에 복원하는 목적
- 각 Manager의 `{domain}_info()` 메서드를 호출해 데이터 로드 (Manager가 알아서 캐싱)

**반환**: 모든 도메인 데이터를 하나의 딕셔너리로 집계해 클라이언트에 전달

---

### GameDataManager.py

**역할**: CSV 메타 데이터를 서버 시작 시 1회 메모리 로드 (api_code: 1002)

**구현 방식**:
- 클래스 변수 `REQUIRE_CONFIGS`에 모든 설정 저장 (싱글톤 패턴)
- `_loaded` 플래그로 중복 로드 방지
- `initialize()` → CSV 파일 8개를 pandas로 읽어 중첩 딕셔너리 구조로 변환
  - building: `{building_idx: {lv: {cost, time, required_buildings}}}`
  - research: `{research_idx: {lv: {buff_idx, cost, time, required_researches}}}`
  - unit: `{unit_idx: {cost, time, ability, required_researches}}`
  - buff: `{buff_idx: {buff_type, effect_type, target_type, stat_type, value_type}}`
  - item: `{item_idx: {category, sub_category, value}}`
  - shop: `{item_idx: {weight}}`
  - mission: `{mission_idx: {category, target_idx, value, reward: {item_idx: quantity}}}`
  - mission_index (자동 생성): `{category: {target_idx: [mission_idx, ...]}}` ← 미션 빠른 조회용 역인덱스
- Game Manager들이 `GameDataManager.REQUIRE_CONFIGS['building'][101][1]` 형태로 직접 조회

**주의**: `get_all_configs()`는 전체 config를 그대로 반환하므로 응답 크기가 큼. 클라이언트가 1회만 호출.

---

### UserInitManager.py

**역할**: 신규 유저 생성 (api_code: 1003)

**구현 방식**:
- DB에 `StatNation` 레코드 생성 (user_no 발급)
- 기본 자원 초기화 (Resources 테이블)
- 초기 데이터 Redis 캐싱

---

### WebsocketManager.py

**역할**: WebSocket 연결 관리 및 메시지 브로드캐스트

**구현 방식**:
- `connections: Dict[int, WebSocket]` 딕셔너리로 user_no → WebSocket 매핑 관리
- `connect(websocket, user_no)`: 연결 등록
- `disconnect(user_no)`: 연결 해제
- `send_personal_message(message, user_no)`: 특정 유저에게 메시지 전송
- `BackgroundWorkerManager`의 `TaskWorker`에서 게임 작업 완료 시 호출

---

### SystemManager.py

**역할**: 공통 유틸리티 함수 모음

---

## 레이어 내 데이터 흐름

```
POST /api (main.py)
    ↓ FastAPI Depends
APIManager(db_manager, redis_manager)
    ↓ api_code 기반 라우팅
GameManager(db_manager, redis_manager).method()
    ↓ 결과 반환
JSONResponse
```

로그인 특이사항:
```
LoginManager.handle_user_login()
    ↓ Phase1 asyncio.gather()
    [BuildingManager.building_info(), UnitManager.unit_info(), ...]
    ↓ Phase2 asyncio.gather()
    [BuffManager.buff_info(), MissionManager.mission_info()]
    ↓ Task 재등록 asyncio.gather()
    [unit_redis.register_active_tasks_to_queue(), research_redis.register_active_tasks_to_queue()]
    ↓ 집계
    {buildings, units, researches, resources, buffs, items, missions, shops}
```
