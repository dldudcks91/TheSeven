# services/db_manager - DB 접근 레이어

## 역할

MySQL 데이터베이스와의 모든 직접 통신을 담당하는 레이어. SQLAlchemy ORM을 사용하며 Game Manager 레이어에서 직접 DB에 접근하지 않고 반드시 이 레이어를 통함.

**사용 시점**:
1. Redis 캐시 미스 → DB에서 초기 데이터 로드 후 Redis 캐싱
2. 신규 레코드 생성 (건물 최초 생성 등, DB 원본 레코드가 필요한 경우)
3. SyncWorker가 Redis dirty data → MySQL 동기화

---

## 파일 목록

### DBManager.py

**역할**: 모든 도메인별 DB Manager의 중앙 접근점 (Facade 패턴)

**구현 방식**:
- 각 도메인 Manager를 lazy initialization (싱글톤 패턴)으로 생성
- `get_building_manager()`, `get_unit_manager()`, ... 등 게터 메서드 제공
- 첫 호출 시 인스턴스 생성 후 캐싱, 이후 동일 인스턴스 재사용
- `commit()`, `rollback()`, `close()`: 트랜잭션 관리 위임

```python
db_manager = DBManager(db_session)
building_db = db_manager.get_building_manager()  # lazy init
result = building_db.get_user_buildings(user_no)
```

---

### base_db_manager.py

**역할**: 모든 도메인 DB Manager의 공통 기반 클래스 (Abstract Base Class)

**제공하는 공통 CRUD**:
- `create(**kwargs)`: 레코드 생성
- `get_by_id(record_id)`: ID로 조회
- `update(record_id, **kwargs)`: 업데이트
- `delete(record_id)`: 삭제
- `get_all(limit, offset, filters)`: 전체 조회 (페이징 + 필터 지원)
- `bulk_create(records_data)`: 벌크 생성
- `get_by_user(user_no, **filters)`: user_no 기준 조회

**공통 응답 형식**:
```python
{
    "success": True/False,
    "message": "...",
    "data": ...,
    "timestamp": "ISO 형식 UTC"
}
```

**에러 처리**: `_handle_db_error()` → SQLAlchemy 예외 시 자동 rollback + 에러 응답 반환

**추상 메서드**: `get_model_class()` → 하위 클래스가 해당 SQLAlchemy 모델 반환

---

### building_db_manager.py

**역할**: Building 테이블 CRUD

**주요 메서드**:
- `get_user_buildings(user_no)`: 유저의 모든 건물 조회
- `create_building(user_no, building_idx, building_lv, status, start_time, end_time, last_dt)`: 건물 최초 생성
- `bulk_upsert_buildings(user_no, buildings_data)`: SyncWorker용 벌크 upsert (Redis → DB 동기화)

---

### unit_db_manager.py

**역할**: Unit 테이블 CRUD

**주요 메서드**:
- `get_user_units(user_no)`: 유저의 모든 유닛 조회
- `bulk_upsert_units(user_no, units_data)`: SyncWorker용 벌크 upsert

---

### research_db_manager.py

**역할**: Research 테이블 CRUD

**주요 메서드**:
- `get_user_researches(user_no)`: 유저의 모든 연구 조회
- `bulk_upsert_researches(user_no, researches_data)`: SyncWorker용 벌크 upsert

---

### resource_db_manager.py

**역할**: Resources 테이블 CRUD

**주요 메서드**:
- `get_user_resources(user_no)`: 유저 자원 조회 (ORM 모델 반환)
- `bulk_upsert_resources(user_no, raw_data)`: SyncWorker용 자원 동기화

---

### buff_db_manager.py

**역할**: Buff 테이블 CRUD

---

### item_db_manager.py

**역할**: Item 테이블 CRUD

**주요 메서드**:
- `bulk_upsert_item(user_no, item_idx, item_data)`: 개별 아이템 upsert
  - ItemSyncWorker는 `{user_no}:{item_idx}` 단위로 dirty flag를 추적하므로 개별 처리

---

### mission_db_manager.py

**역할**: UserMission 테이블 CRUD

**주요 메서드**:
- `bulk_upsert_missions(user_no, missions_data)`: SyncWorker용 벌크 upsert

---

### shop_db_manager.py

**역할**: Shop 관련 테이블 CRUD

---

### alliance_db_manager.py

**역할**: Alliance, AllianceMember, AllianceApplication, AllianceResearch 테이블 CRUD

**주요 메서드**:
- `upsert_alliance(alliance_id, info)`: 연맹 기본 정보 upsert
- `upsert_member(alliance_id, user_no, member_data)`: 멤버 upsert
- `upsert_application(alliance_id, user_no, app_data)`: 신청자 upsert
- `upsert_research(alliance_id, research_idx, research_data)`: 연맹 연구 upsert
- `delete_all_members(alliance_id)`: 연맹 멤버 전체 삭제 (동기화 전 초기화용)
- `delete_all_applications(alliance_id)`: 신청자 전체 삭제
- `delete_alliance(alliance_id)`: 연맹 삭제 (해산 시)

---

### user_init_db_manager.py

**역할**: 신규 유저 초기화 (StatNation, Resources 초기 레코드 생성)

---

### codex_db_manager.py

**역할**: 도감 데이터 CRUD

---

### db_types.py

**역할**: `TableType` Enum 정의 (각 Manager가 자신의 테이블 타입을 식별하는 데 사용)

---

## 아키텍처 특징

### Redis-First 원칙

DB Manager는 Game Manager가 직접 호출하는 경우가 제한적:
1. **Redis 캐시 미스** 시 폴백으로 호출
2. **신규 레코드 생성** (building_create 등) - 레코드 ID가 필요할 때
3. **SyncWorker** - 주기적 Redis → DB 동기화

### 세션 관리

- `main.py`에서 FastAPI Depends로 DB 세션 주입
- SyncWorker는 별도 `SessionLocal()` 세션 생성 (워커 전용)
- `DBManager.commit()` / `rollback()` / `close()`로 명시적 트랜잭션 관리

### Bulk Upsert 패턴

SyncWorker에서 사용하는 패턴. Redis의 Hash 전체를 읽어 DB에 INSERT OR UPDATE:
```python
# SyncWorker에서
raw_data = await redis.hgetall(f"user_data:{user_no}:building")
db_manager.get_building_manager().bulk_upsert_buildings(user_no, raw_data)
```
