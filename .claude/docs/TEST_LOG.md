# Test Log

테스트 검증 결과를 도메인별로 기록한다.
각 테스트의 목적, 결과, 발견 사항, 추후 변화를 트래킹한다.

---

## Building (2xxx)

**테스트 파일**: `fastapi/tests/test_building.py`
**실행일**: 2026-03-06
**결과**: 26 passed / 0 failed (1.64s)

### 테스트 인프라 특이사항

| 항목 | 내용 |
|------|------|
| fakeredis Lua 미지원 | `atomic_consume`을 non-Lua 방식으로 conftest에서 패치. 단일 스레드 테스트이므로 원자성 불필요 |
| speedup API 미등록 | `building_speedup` 메서드는 존재했으나 api_code 미등록 → 2007로 등록 |

### 테스트 목록

#### 2001 - 건물 정보 조회 (TestBuildingInfo)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_info_no_user | 유저 없이 조회 → 빈 데이터 반환 | PASS |
| test_info_no_buildings | 유저 있고 건물 없을 때 → 빈 dict | PASS |
| test_info_with_building | Redis에 건물 존재 시 데이터 반환 | PASS |

#### 2002 - 건물 생성 (TestBuildingCreate)

| 테스트 | 목적 | 결과 | 비고 |
|--------|------|------|------|
| test_create_success | 정상 생성: status=1, building_lv=0 | PASS | |
| test_create_duplicate | 이미 존재하는 건물 재생성 → 실패 | PASS | |
| test_create_invalid_building_idx | 존재하지 않는 building_idx → 실패 | PASS | |
| test_create_missing_building_idx | building_idx 누락 → 실패 | PASS | |
| test_create_consumes_resources | 자원 소모 확인 (201 Lv1: food=100) | PASS | BUG #1 발견: 자원 체크 로직 문제 |

#### 2003 - 건물 업그레이드 (TestBuildingUpgrade)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_upgrade_success | 정상 업그레이드: status=2, target_level=2 | PASS |
| test_upgrade_not_found | 건물 없을 때 업그레이드 → 실패 | PASS |
| test_upgrade_already_in_progress | 이미 진행 중 → 실패 | PASS |
| test_upgrade_max_level | 최대 레벨(10) → 실패 | PASS |
| test_upgrade_consumes_resources | 자원 소모 확인 (201 Lv2: food=200) | PASS |

#### 2007 - 건물 가속 (TestBuildingSpeedup)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_speedup_success | 정상 가속 → end_time 단축 | PASS |
| test_speedup_not_upgrading | status != 2 → 실패 | PASS |
| test_speedup_invalid_seconds | speedup_seconds <= 0 → 실패 | PASS |

#### 2004 - 건물 완료 (TestBuildingFinish)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_finish_upgrade_via_speedup | 업그레이드 → 가속 → 완료 전체 흐름 | PASS |
| test_finish_not_in_progress | 진행 중 아닌 건물 완료 → 실패 | PASS |
| test_finish_time_not_reached | 시간 미도달 → 실패 + remaining 메시지 | PASS |
| test_finish_not_found | 존재하지 않는 건물 → 실패 | PASS |

#### 2005 - 건물 취소 (TestBuildingCancel)

| 테스트 | 목적 | 결과 | 비고 |
|--------|------|------|------|
| test_cancel_upgrade | 업그레이드 중 취소 → status 복구 + 자원 환불 | PASS | |
| test_cancel_not_in_progress | 진행 중 아닌 건물 취소 → 실패 | PASS | |
| test_cancel_construction | 건설 중(status=1) 취소 → Redis 삭제 + 환불 | PASS | BUG #2: DB 레코드 미삭제 |

#### 2006 - 일괄 완료 (TestBuildingFinishAll)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_finish_all_none | 완료 건물 없음 → 빈 리스트 | PASS |
| test_finish_all_with_completed | 2개 건물 가속 후 일괄 완료 | PASS |

#### 기타

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_invalid_api_code | 미등록 api_code → 400 | PASS |

### 발견된 버그

| ID | 위치 | 심각도 | 내용 | 상태 |
|----|------|--------|------|------|
| BUG #1 | BuildingManager.building_create:279 | 중 | `not dict`은 항상 False → 자원 부족 검사 무시 | 수정 완료 |
| BUG #2 | BuildingManager.building_cancel:784 | 중 | 건설 취소 시 Redis만 삭제, DB 레코드 잔존 → 재조회 시 복원 | 수정 완료 |
| BUG #3 | BuildingManager._apply_building_buffs:283 | 경 | async 함수를 await 없이 호출 → coroutine never awaited | 수정 완료 |

### 미검증 항목

- 자원 부족 시 building_create 실패 테스트 (BUG #1 수정 후 추가 필요)
- building_cancel(status=1) 후 재조회 시 DB 데이터 미반환 테스트 (BUG #2 수정 후 추가 필요)
- 버프 적용 시 건설 시간 단축 테스트 (BUG #3 수정 후 추가 필요)

---

## Research (3xxx)

**테스트 파일**: `fastapi/tests/test_research.py`
**실행일**: 2026-03-06
**결과**: 16 passed / 0 failed (1.34s)

### 테스트 목록

#### 3001 - 연구 정보 조회 (TestResearchInfo)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_info_empty | 연구 데이터 없는 초기 상태 → 빈 목록 | PASS |
| test_info_with_data | Redis에 완료 연구 존재 시 정상 조회 | PASS |

#### 3002 - 연구 시작 (TestResearchStart)

| 테스트 | 목적 | 결과 | 비고 |
|--------|------|------|------|
| test_start_success | 정상 시작 (1001 Lv1: food=100, gold=100, 20s) | PASS | |
| test_start_insufficient_resources | 자원 부족 → 실패 | PASS | |
| test_start_duplicate | 이미 진행 중인 연구 있을 때 → 거부 | PASS | |
| test_start_missing_params | research_idx/research_lv 누락 → 실패 | PASS | |
| test_start_invalid_config | 존재하지 않는 연구 idx → 실패 | PASS | |

#### 3003 - 연구 완료 (TestResearchFinish)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_finish_success | 시간 경과 후 정상 완료, research_lv 0→1 | PASS |
| test_finish_not_ready | 시간 미경과 → 실패 + remaining 메시지 | PASS |
| test_finish_not_processing | 진행 중 아닌 연구 완료 시도 → 실패 | PASS |
| test_finish_nonexistent | 존재하지 않는 연구 완료 시도 → 실패 | PASS |

#### 3004 - 연구 취소 (TestResearchCancel)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_cancel_success | 취소 + 50% 자원 환불 (food=50, gold=50) | PASS |
| test_cancel_not_processing | 진행 중 아닌 연구 취소 → 실패 | PASS |

#### 통합 플로우 (TestResearchFlow)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_full_flow_start_to_finish | 시작(3002) → end_time 과거로 변경 → 완료(3003) | PASS |
| test_start_cancel_restart | 시작(3002) → 취소(3004) → 재시작(3002) | PASS |

#### 기타

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_unknown_api_code | 미등록 api_code 3999 → HTTP 400 | PASS |

### 발견된 버그

| ID | 위치 | 심각도 | 내용 | 상태 |
|----|------|--------|------|------|
| BUG #1 | ResearchManager._apply_research_buffs:339 | 경 | sync 함수에서 async `get_total_buffs_by_type` 호출 → coroutine never awaited | 수정 완료 |
| BUG #2 | ResearchManager._check_research_availability:291 | 고 | `prerequisite_research` 키 사용하지만 실제 키는 `required_researches` + config 구조 불일치 → 선행 연구 체크 항상 AVAILABLE | 수정 완료 |
| BUG #3 | ResearchManager._unlock_dependent_researches:662 | 고 | BUG #2와 동일한 패턴 → 후속 연구 잠금 해제 불가 | 수정 완료 |

### 미검증 항목

- 선행 연구 미완료 시 LOCKED 상태 검증 (BUG #2 수정 후 추가 가능)
- 연구 완료 후 후속 연구 UNLOCK 검증 (BUG #3 수정 후 추가 가능)
- 버프 적용 시 연구 시간 단축 테스트 (BUG #1 수정 후 추가 가능)

---

## Unit (4xxx)

**테스트 파일**: `fastapi/tests/test_unit.py`
**실행일**: 2026-03-06
**결과**: 28 passed / 0 failed (1.54s)

### 테스트 인프라 특이사항

| 항목 | 내용 |
|------|------|
| fakeredis Lua 미지원 | Building/Research와 동일, `atomic_consume` non-Lua 패치 |

### 테스트 목록

#### 4001 - 유닛 정보 조회 (TestUnitInfo)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_info_empty | 유닛 없는 상태 → 빈 데이터 | PASS |
| test_info_with_unit | Redis에 유닛 존재 시 정상 조회 | PASS |

#### 4002 - 유닛 훈련 (TestUnitTrain)

| 테스트 | 목적 | 결과 | 비고 |
|--------|------|------|------|
| test_train_success | 정상 훈련: training 증가 | PASS | |
| test_train_missing_unit_idx | unit_idx 누락 → 실패 | PASS | |
| test_train_invalid_unit_idx | 존재하지 않는 unit_idx → 실패 | PASS | |
| test_train_zero_quantity | quantity 0 → 실패 | PASS | |
| test_train_insufficient_resources | 자원 부족 → 실패 | PASS | |
| test_train_duplicate_same_type | 동일 unit_type 중복 훈련 → 거부 | PASS | BUG #2 발견 |
| test_train_consumes_resources | 자원 소모 확인 (401×5: food=500) | PASS | |
| test_train_different_type_allowed | 다른 unit_type은 동시 훈련 가능 | PASS | |

#### 4003 - 유닛 업그레이드 (TestUnitUpgrade)

| 테스트 | 목적 | 결과 | 비고 |
|--------|------|------|------|
| test_upgrade_success | 정상 업그레이드: ready 감소, upgrading 증가 | PASS | |
| test_upgrade_not_enough_ready | ready 부족 → 실패 | PASS | |
| test_upgrade_missing_target | target_unit_idx 누락 → 실패 | PASS | |
| test_upgrade_duplicate_same_type | 동일 unit_type 작업 중 → 거부 | PASS | BUG #2 발견 |
| test_upgrade_consumes_resources | 자원 소모 확인 (402×3: food=600) | PASS | |

#### 통합 플로우 (TestUnitFlow)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_train_then_info | 훈련 시작 → info에 training 반영 | PASS |
| test_upgrade_updates_ready_and_upgrading | 업그레이드 → ready/upgrading 변화 확인 | PASS |

#### 4004 - 유닛 완료 (TestUnitFinish)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_finish_success | 시간 경과 후 완료 → training=0, ready=5 | PASS |
| test_finish_not_ready | 시간 미경과 → 실패 + remaining 메시지 | PASS |
| test_finish_no_task | 진행 중 작업 없이 완료 시도 → 실패 | PASS |

#### 4005 - 유닛 취소 (TestUnitCancel)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_cancel_train_success | 훈련 취소 + 자원 100% 환불 | PASS |
| test_cancel_upgrade_success | 업그레이드 취소 + ready 복원 + 자원 환불 | PASS |
| test_cancel_no_task | 유닛 존재하지만 작업 없이 취소 → 실패 | PASS |
| test_cancel_invalid_unit | 존재하지 않는 unit_idx → 실패 | PASS |

#### 4006 - 유닛 즉시 완료 (TestUnitSpeedup)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_speedup_success | 즉시 완료 → completion_time 변경 | PASS |
| test_speedup_no_task | 작업 없이 speedup → 실패 | PASS |
| test_speedup_then_finish | speedup → finish → training=0, ready=5 | PASS |

#### 기타

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_unknown_api_code | 미등록 api_code 4999 → HTTP 400 | PASS |

### 발견된 버그

| ID | 위치 | 심각도 | 내용 | 상태 |
|----|------|--------|------|------|
| BUG #1 | UnitManager._apply_unit_buffs:325 | 경 | sync 함수에서 async `get_total_buffs_by_type` 호출 → 'coroutine' object is not iterable | 수정 완료 |
| BUG #2 | UnitManager._has_ongoing_task:288 | 고 | member key `{user_no}:{unit_type}`으로 조회하지만 실제 저장은 `{user_no}:{unit_type}:{unit_idx}` → 중복 체크 항상 실패 | 수정 완료 |
| BUG #3 | UnitManager._format_unit_data:225 | 중 | `get_unit_completion_time(user_no, unit_idx)` — unit_type 누락으로 completion_time 항상 None | 수정 완료 |
| ISSUE #1 | UnitManager.unit_cancel/speedup/get_completion_status | 고 | DB `models.UnitTasks` 미존재로 AttributeError → Redis 기반으로 전환 | 수정 완료 |
| ISSUE #2 | UnitRedisManager.invalidate_unit_cache:202 | 중 | `_get_units_meta_key` 미정의 메서드 호출 → `cache_manager.get_user_data_meta_key`로 수정 | 수정 완료 |
| BUG #4 | UnitRedisManager.update_unit_completion_time:67 | 중 | `unit_idx`를 `task_id`로 전달하지만 실제 `task_id`는 `unit_type` → key 불일치 | 수정 완료 |

### 미검증 항목

- 버프 적용 시 훈련 시간 단축 테스트
- `unit_db_manager.py`의 UnitTasks 관련 죽은 코드 정리

---

## Buff (1012)

**테스트 파일**: `fastapi/tests/test_buff.py`
**실행일**: 2026-03-06
**결과**: 10 passed / 0 failed (1.39s)

### 테스트 목록

#### 1012 - 버프 정보 조회 (TestBuffInfo)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_info_empty | 버프 없는 상태 → 빈 데이터 | PASS |
| test_info_with_permanent_buff | 영구 버프 설정 → 정상 조회 | PASS |
| test_info_with_temporary_buff | 임시 버프 설정 → 정상 조회 | PASS |
| test_info_total_sums_all_sources | 영구(5) + 임시(10) → total = 15 | PASS |
| test_info_multiple_target_types | unit + resource → 각각 분리 조회 | PASS |

#### Total Buffs 계산 검증 (TestTotalBuffsCalculation)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_multiple_sources_same_key | 동일 stat 키에 여러 소스(5+3) → 합산 8 | PASS |
| test_sub_type_all_separate_key | sub_type=all → 별도 키로 집계 | PASS |
| test_multiple_temp_buffs_summed | 임시 버프 3개(5+5+5) → total = 15 | PASS |
| test_different_stat_types_independent | attack과 speed → 독립 집계 | PASS |

#### 기타

| 테스트 | 목적 | 결과 |
|--------|------|------|
| test_unregistered_buff_total_api | 미등록 API 코드 1111 → HTTP 400 | PASS |

### 발견된 이슈

| ID | 위치 | 심각도 | 내용 | 상태 |
|----|------|--------|------|------|
| ISSUE #1 | APIManager | 중 | buff_total_info/buff_total_by_type_info 메서드 존재하지만 api_code 미등록. 클라이언트 buff.html에서 1111 호출 시 400 에러 | 미해결 |
| ISSUE #2 | base_redis_task_manager.get_completed_tasks:82 | 중 | `parsed['sub_id']` 무조건 참조 → buff는 2-part key로 sub_id 없음 → KeyError → TaskWorker 만료 처리 크래시 | 미해결 |

### 미검증 항목

- 임시 버프 만료 후 자동 제거 (TaskWorker 연동, ISSUE #2 해결 필요)
- 연구 완료 시 영구 버프 자동 추가 (cross-domain 통합 테스트)
- 아이템 사용 시 임시 버프 추가 (cross-domain 통합 테스트)
