# services/background_workers - 백그라운드 워커 레이어

## 역할

서버 시작 후 백그라운드에서 지속적으로 실행되는 비동기 태스크 모음. 두 가지 목적:

1. **SyncWorker**: Redis(메인 저장소)의 변경 데이터를 주기적으로 MySQL에 영속화
2. **TaskWorker**: 완료 시각이 지난 게임 작업(유닛 훈련 완료 등)을 실시간 처리 + WebSocket 알림

---

## 파일 목록

### BackgroundWorkerManager.py

**역할**: 모든 백그라운드 워커의 생명주기 관리

**관리하는 워커**:
```
SyncWorkers:
  - building    (10초 주기)
  - research    (10초 주기)
  - unit        (30초 주기)
  - alliance    (30초 주기)
  - resources   (60초 주기)
  - item        (60초 주기)
  - mission    (120초 주기)

TaskWorker:
  - game_task   (1초 주기)
```

**주요 메서드**:
- `initialize(redis_manager, websocket_manager, config)`: 워커 인스턴스 생성
- `start_all_workers()`: 모든 워커를 `asyncio.create_task(worker.start())`로 시작
- `stop_all_workers()`: 종료 전 강제 동기화 실행 후 모든 워커 중지
- `start_worker(worker_name)` / `stop_worker(worker_name)`: 개별 워커 제어
- `get_all_worker_status()`: 각 워커의 상태 딕셔너리 반환

**종료 시퀀스**: 서버 shutdown 이벤트 → 각 워커 `force_sync_all()` 실행 (미반영 데이터 강제 flush) → 워커 stop → asyncio Task cancel

---

### base_worker.py - BaseWorker

**역할**: 모든 워커의 공통 기반 클래스

**핵심 루프**:
```python
async def start(self):
    self._running = True
    while self._running:
        await self._process_pending()
        await asyncio.sleep(self._check_interval)
```

**추상 메서드 (하위 클래스 구현)**:
- `_get_pending_users()`: dirty flag Set에서 대기 중인 user_no 목록 반환
- `_remove_from_pending(user_no)`: 처리 완료 후 dirty flag에서 제거
- `_sync_user(user_no, db_session)`: 실제 동기화 로직

**공통 `_process_pending()` 기본 구현** (SyncWorker용):
1. `smembers(sync_pending:{category})` → pending user 목록
2. DB 세션 생성
3. 각 user_no에 대해 `_sync_user()` 실행
4. 성공 시 `_remove_from_pending()`, 실패 시 dirty flag 유지 (다음 주기 재시도)
5. DB 세션 close

**상태 추적**: `_sync_count`, `_error_count`, `_last_sync_time`

---

### sync_worker.py

**역할**: 7개 도메인의 Redis → MySQL 동기화 워커 구현

**공통 동작 패턴**:
```python
# 1. Game Manager가 Redis에 데이터 갱신 시:
redis.sadd(f"sync_pending:{category}", user_no)  # dirty flag 설정

# 2. SyncWorker가 주기적으로:
pending_users = await redis.smembers(f"sync_pending:{category}")
for user_no in pending_users:
    raw_data = await redis.hgetall(f"user_data:{user_no}:{category}")
    db_manager.get_{category}_manager().bulk_upsert_{category}(user_no, raw_data)
    db_session.commit()
    await redis.srem(f"sync_pending:{category}", user_no)  # dirty flag 제거
```

**각 워커 세부 사항**:

| 워커 | 주기 | Dirty Key | Redis Key 패턴 | DB 메서드 |
|------|------|-----------|----------------|-----------|
| BuildingSyncWorker | 10s | `sync_pending:building` | `user_data:{no}:building` | `bulk_upsert_buildings()` |
| ResearchSyncWorker | 10s | `sync_pending:research` | `user_data:{no}:research` | `bulk_upsert_researches()` |
| UnitSyncWorker | 30s | `sync_pending:unit` | `user_data:{no}:unit` | `bulk_upsert_units()` |
| AllianceSyncWorker | 30s | `sync_pending:alliance` | `alliance:{id}:*` | `upsert_alliance()` 등 |
| ResourceSyncWorker | 60s | `sync_pending:resources` | `user_data:{no}:resources` | `bulk_upsert_resources()` |
| ItemSyncWorker | 60s | `sync_pending:item` | `user_data:{no}:item` | `bulk_upsert_item()` |
| MissionSyncWorker | 120s | `sync_pending:mission` | `user_data:{no}:mission` | `bulk_upsert_missions()` |

**주기 설계 근거** (BackgroundWorkerManager 주석 기준):
- 10초: 변경 빈도 낮음 + 유실 영향 높음 (건물/연구)
- 30초: 변경 빈도 중간 + 유실 영향 높음 (유닛/연맹)
- 60초: 변경 빈도 높음 + 유실 영향 중간 (자원/아이템)
- 120초: 변경 빈도 낮음 + 유실 영향 낮음 (미션)

**AllianceSyncWorker 특이사항**:
- Dirty flag의 member가 `user_no`가 아닌 `alliance_id`
- Redis에서 연맹 info가 없으면 → 해산된 연맹으로 판단 → DB에서 관련 데이터 전체 삭제
- 멤버/신청자 동기화는 DB 전체 삭제 후 Redis 현재 상태로 덮어쓰기

**ItemSyncWorker 특이사항**:
- Dirty flag member가 `{user_no}:{item_idx}` 형태 (개별 아이템 추적)
- `_process_pending()`을 완전히 오버라이드해 개별 처리

---

### task_worker.py - TaskWorker

**역할**: 완료 시각이 지난 게임 작업을 1초 주기로 감지하고 처리

**현재 처리 대상**:
- 유닛 훈련 완료 (`completion_queue:unit` Sorted Set)

**동작 흐름**:
```
1초마다:
    UnitManager.get_completed_units_for_worker()
        → ZRANGEBYSCORE(completion_queue:unit, 0, now)
        → 완료된 (user_no, unit_type, unit_idx) 목록

    for task in completed_tasks:
        UnitManager.unit_finish()
            → Redis 캐시 갱신 (유닛 수량 증가, 상태 업데이트)
            → sync_pending:unit에 dirty flag 설정

        WebsocketManager.send_personal_message(user_no, 'unit_finish', result)
```

**주의**: SyncWorker와 달리 `_get_pending_users()`, `_sync_user()`, `_remove_from_pending()`을 사용하지 않고 `_process_pending()`만 오버라이드. 추상 메서드들은 빈 구현(pass)으로 처리.

---

## 전체 데이터 플로우

```
Game API 호출 (예: unit_train)
    ↓
UnitManager.unit_train()
    └─ Redis Task Queue에 완료 시각 등록
       (ZADD completion_queue:unit {user_no}:{unit_type}:{unit_idx} {timestamp})

    (1초 후, TaskWorker)
    ↓
TaskWorker._handle_unit_tasks()
    └─ ZRANGEBYSCORE → 완료된 작업 감지
    └─ UnitManager.unit_finish() → Redis 캐시 갱신
       └─ SADD sync_pending:unit {user_no}  (dirty flag)
    └─ WebSocket 알림 전송

    (30초 후, UnitSyncWorker)
    ↓
UnitSyncWorker._sync_user(user_no)
    └─ HGETALL user_data:{user_no}:unit → Redis 현재 상태
    └─ bulk_upsert_units() → MySQL 반영
    └─ SREM sync_pending:unit {user_no}  (dirty flag 제거)
```
