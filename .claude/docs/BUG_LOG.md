# Bug Log

테스트 및 코드 리뷰에서 발견된 버그와 이슈를 기록한다.

---

## [2026-03-06] Building 테스트 검증

### 즉시 수정한 버그

#### BUG #1 - building_create 자원 체크 우회 ✅

- 발생 위치: `services/game/BuildingManager.py` / `building_create` (line 279)
- 원인: `if not await resource_manager.consume_resources(user_no, costs):`에서 `consume_resources`는 dict를 반환. dict는 비어있지 않으면 항상 truthy이므로 `not dict`은 항상 `False`. 자원 부족이어도 조건문에 진입하지 않음.
- 해결: `consume_result = await resource_manager.consume_resources(...)` 후 `if not consume_result["success"]:` 패턴으로 수정. 부족 시 shortage 정보도 응답에 포함.

#### BUG #2 - building_cancel(status=1) DB 레코드 미삭제 ✅

- 발생 위치: `services/game/BuildingManager.py` / `building_cancel` (line 784)
- 원인: 건설 중(status=1) 취소 시 `remove_cached_building`으로 Redis 캐시만 삭제. `building_create`에서 DB에 직접 INSERT한 레코드는 삭제하지 않음.
- 해결: status=1일 때 `building_db.delete_building(user_no, building_idx)` + `db_manager.commit()` 추가.

#### BUG #3 - _apply_building_buffs에서 async 함수 미대기 ✅

- 발생 위치: `services/game/BuildingManager.py` / `_apply_building_buffs` (line 837)
- 원인: `BuffManager.get_total_buffs_by_type`이 async 함수인데 `_apply_building_buffs`는 동기 함수. `await` 없이 호출하여 coroutine 객체만 반환되고 실제 실행되지 않음.
- 해결: `_apply_building_buffs`를 `async`로 변경하고, 호출부(`building_create`, `building_upgrade`)에서 `await` 추가.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- fakeredis가 Lua 스크립트(`EVAL`)를 지원하지 않아 `conftest.py`에서 `atomic_consume`을 non-Lua로 패치. 실제 Redis와 동작 차이가 있을 수 있음.

---

## [2026-03-06] Research 테스트 검증

### 즉시 수정한 버그

#### BUG #1 - _apply_research_buffs에서 async 함수 미대기 ✅

- 발생 위치: `services/game/ResearchManager.py` / `_apply_research_buffs` (line 339)
- 원인: `BuffManager.get_total_buffs_by_type`이 async 함수인데 `_apply_research_buffs`는 sync 함수. `await` 없이 호출하여 coroutine 객체만 반환. Building BUG #3과 동일 패턴.
- 해결: `_apply_research_buffs`를 `async`로 변경, 호출부(`research_start`)에서 `await` 추가.

#### BUG #2 - _check_research_availability 잘못된 키/구조 접근 ✅

- 발생 위치: `services/game/ResearchManager.py` / `_check_research_availability` (line 291)
- 원인: `config.get('prerequisite_research')` 사용하지만 실제 키는 `required_researches`. 또한 `REQUIRE_CONFIGS['research'][research_idx]`는 `{lv: config_data}` 구조인데 flat dict처럼 접근. 결과적으로 선행 연구 체크가 항상 None을 반환하여 모든 연구가 AVAILABLE로 판정.
- 해결: 레벨 1 config에서 `required_researches` 키를 조회하고, `[(prereq_idx, prereq_lv)]` 형식으로 선행 연구 완료 여부 확인하도록 수정.

#### BUG #3 - _unlock_dependent_researches 잘못된 키/구조 접근 ✅

- 발생 위치: `services/game/ResearchManager.py` / `_unlock_dependent_researches` (line 662)
- 원인: BUG #2와 동일. `config.get('prerequisite_research')` 사용 + config 구조 불일치로 후속 연구 잠금 해제가 동작하지 않음.
- 해결: 레벨별 config 구조에 맞게 순회 방식 변경. `_check_research_availability` 재활용하여 다중 선행 조건도 처리.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- Building과 동일하게 fakeredis Lua 패치 적용 환경에서 테스트.
- 선행 연구 체크 로직은 수정했으나, 실제 선행 연구 잠금/해제 플로우 테스트는 미작성 (미검증 항목).

---

## [2026-03-06] Unit 테스트 검증

### 즉시 수정한 버그

#### BUG #1 - _apply_unit_buffs에서 async 함수 미대기 ✅

- 발생 위치: `services/game/UnitManager.py` / `_apply_unit_buffs` (line 325)
- 원인: `BuffManager.get_total_buffs_by_type`이 async 함수인데 `_apply_unit_buffs`는 sync 함수. `await` 없이 호출하여 coroutine 객체 반환 → `'coroutine' object is not iterable` 에러. Building/Research BUG와 동일 패턴.
- 해결: `_apply_unit_buffs`를 `async`로 변경, 호출부(`unit_train`)에서 `await` 추가.

#### BUG #2 - _has_ongoing_task member key 불일치 ✅

- 발생 위치: `services/game/UnitManager.py` / `_has_ongoing_task` (line 288)
- 원인: `get_unit_completion_time(user_no, unit_type)`으로 호출하면 member key가 `{user_no}:{unit_type}`이 되지만, `add_unit_to_queue`에서 `sub_id=unit_idx`를 포함하여 `{user_no}:{unit_type}:{unit_idx}`로 저장. `zscore` 정확 매칭이므로 절대 찾을 수 없음 → 동일 타입 중복 훈련/업그레이드 허용.
- 해결: `UnitRedisManager.has_ongoing_task_for_type()` 메서드 추가. `zrange`로 전체 멤버를 조회하여 `{user_no}:{unit_type}:` prefix 매칭. `_has_ongoing_task`에서 이 메서드 사용.

#### BUG #3 - _format_unit_data에서 get_unit_completion_time 인자 누락 ✅

- 발생 위치: `services/game/UnitManager.py` / `_format_unit_data` (line 225)
- 원인: `get_unit_completion_time(user_no, unit_idx)` 호출 시 `unit_idx`가 `unit_type` 파라미터 위치에 전달됨. 실제 시그니처는 `(user_no, unit_type, unit_idx)`. member key가 `{user_no}:{unit_idx}`가 되어 매칭 실패 → completion_time 항상 None.
- 해결: `UNIT_TYPE_MAP`에서 `unit_type`을 조회하고, `get_unit_completion_time(user_no, unit_type, unit_idx)` 3인자로 호출.

### 미해결 이슈

(없음 — ISSUE #1, #2 모두 해결 완료)

### 해결된 이전 미해결 이슈

#### ISSUE #1 - UnitTasks 모델 미존재 → Redis 기반으로 전환 ✅

- 원인: `unit_cancel`, `unit_speedup`, `get_completion_status`가 DB `models.UnitTasks`를 참조하지만 모델 미존재.
- 해결: UnitTasks DB 의존을 제거하고 Redis metadata(`get_task_metadata`)로 전환. `unit_cancel`/`unit_speedup`/`get_completion_status` 전부 Redis 기반으로 리팩터. APIManager에 4004(finish)/4005(cancel)/4006(speedup) 등록.

#### ISSUE #2 - invalidate_unit_cache 미정의 메서드 ✅

- 원인: `self._get_units_meta_key(user_no)` 호출하지만 해당 메서드 미정의.
- 해결: `self.cache_manager.get_user_data_meta_key(user_no)`로 수정.

#### 추가 발견 - update_unit_completion_time 인자 불일치 ✅

- 발생 위치: `services/redis_manager/unit_redis_manager.py` / `update_unit_completion_time`
- 원인: `(user_no, unit_idx, new_completion_time, queue_id)` 시그니처에서 `unit_idx`가 `task_id` 위치에 전달됨. 실제로는 `unit_type`이 `task_id`.
- 해결: `(user_no, unit_type, new_completion_time, unit_idx)` 시그니처로 수정.

### 알려진 한계/주의사항
- Building/Research와 동일하게 fakeredis Lua 패치 적용 환경에서 테스트.
- `unit_db_manager.py`의 UnitTasks 관련 메서드(`get_current_task`, `has_ongoing_task`, `get_active_tasks`, `start_unit_train`, `start_unit_upgrade`, `cancel_unit_task`)는 죽은 코드. `models.UnitTasks` 미존재로 런타임 에러 발생하지만 현재 호출되는 곳 없음.

---

## [2026-03-06] Buff 테스트 검증

### 즉시 수정한 버그

(없음)

### 미해결 이슈

#### ISSUE #1 - buff_total_info / buff_total_by_type_info API 미등록

- 발생 위치: `services/system/APIManager.py`
- 원인: `BuffManager.buff_total_info()`와 `buff_total_by_type_info()` 메서드는 존재하지만 APIManager에 api_code 미등록. 클라이언트 `buff.html`에서 API 코드 1111을 호출하지만 400 에러 반환.
- 영향 범위: 클라이언트 버프 UI에서 총합 조회 불가
- 해결 방향: APIManager에 1013(buff_total_info), 1014(buff_total_by_type_info) 등록 필요

#### ISSUE #2 - get_completed_tasks에서 sub_id KeyError 가능성

- 발생 위치: `services/redis_manager/base_redis_task_manager.py` / `get_completed_tasks` (line 82)
- 원인: `parsed['sub_id']`를 무조건 참조하지만, buff는 2-part key(`{user_no}:{buff_id}`)로 `sub_id`가 없음. `_parse_member_key`는 `len(parts) > 2`일 때만 `sub_id`를 추가하므로 KeyError 발생.
- 영향 범위: TaskWorker에서 만료된 임시 버프 처리 시 크래시 → 버프 만료 자동 정리 불가
- 해결 방향: `get_completed_tasks`에서 `parsed.get('sub_id')` 사용으로 변경

### 알려진 한계/주의사항
- buff_info(1012)는 정상 동작. 버프 데이터의 CRUD는 다른 Manager(Research, Item)에서 호출하는 내부 메서드.
- 임시 버프 만료 자동 처리는 ISSUE #2로 인해 TaskWorker에서 동작하지 않을 수 있음.
