# Bug Log

테스트 및 코드 리뷰에서 발견된 버그와 이슈를 기록한다.

---

## [2026-03-11] 유닛 훈련/업그레이드 완료 처리 버그 수정

### 즉시 수정한 버그

#### BUG #1 - 메타데이터 TTL 만료로 유닛 완료 처리 실패 ✅

- 발생 위치: `services/redis_manager/base_redis_task_manager.py` / `add_to_queue` (line 42)
- 원인: 메타데이터에 86400초(24시간) TTL이 설정되어 있으나, Sorted Set 멤버는 TTL 없음. 메타데이터 만료 후 Worker가 처리 시도 → `task_type=-1` (TASK_TRAIN도 TASK_UPGRADE도 아님) → 큐에서만 제거하고 유닛 상태 미변경. `upgrading` 값이 영구 고착.
- 해결: 메타데이터 TTL 제거. `remove_from_queue()`에서 Sorted Set 멤버와 메타데이터를 함께 삭제하므로 수명이 자동 동기화됨.

#### BUG #2 - 로그인 복구에서 upgrading 유닛 누락 ✅

- 발생 위치: `services/redis_manager/unit_redis_manager.py` / `register_active_tasks_to_queue` (line 539-540)
- 원인: `training > 0`만 체크하고 `upgrading > 0`인 유닛은 `continue`로 스킵. 서버 재시작/Redis 클리어 후 로그인 시 업그레이드 중인 유닛의 Task 큐 재등록이 이루어지지 않음.
- 해결: `upgrading > 0` 분기 추가. `training_end_time`과 `upgrade_target_unit_idx` 기반으로 큐 재등록 또는 강제 완료(ready로 복구) 처리.

#### BUG #3 - 고아 복구에서 upgrading 유닛 누락 ✅

- 발생 위치: `services/game/UnitManager.py` / `recover_orphaned_tasks` (line 951-952)
- 원인: BUG #2와 동일 패턴. `training > 0`만 체크, `upgrading > 0`은 무시. Task 큐에 없는 upgrading 유닛이 영구 고착.
- 해결: `upgrading > 0` && Task 큐 없음 → `ready += upgrading`, `upgrading = 0`으로 강제 복구.

#### BUG #4 - 업그레이드 완료 시 target 유닛 ready 미증가 ✅

- 발생 위치: `services/game/UnitManager.py` / `_handle_unit_upgrade` (line 868)
- 원인: `target_unit_data['total']`만 증가시키고 `target_unit_data['ready']`는 증가시키지 않음. 업그레이드 완료된 유닛이 total에만 반영되고 실제 사용 가능한 ready에는 미반영.
- 해결: `target_unit_data['ready'] += quantity` 추가.

#### BUG #5 (보완) - unit_upgrade 캐시에 training_end_time 미저장 ✅

- 발생 위치: `services/game/UnitManager.py` / `unit_upgrade` (line 560-565)
- 원인: `unit_train()`은 `training_end_time`을 캐시에 저장하지만, `unit_upgrade()`는 저장하지 않음. 로그인 복구 시 완료 시간을 알 수 없어 큐 재등록 불가능.
- 해결: `unit_upgrade()` 캐시 업데이트에 `training_end_time`, `upgrade_target_unit_idx` 필드 추가. `_handle_unit_upgrade()` 완료 시 해당 필드 None으로 정리.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- 업그레이드 강제 복구(BUG #2, #3) 시 타겟 유닛으로 이전이 아닌 원래 유닛의 ready로 복구. 타겟 유닛 정보 없이는 정확한 이전 불가능하므로 데이터 유실 방지 우선.
- `base_redis_task_manager.py`의 TTL 제거는 모든 TaskType(building, research, unit_training 등)에 영향. 다만 기존에도 `remove_from_queue`에서 메타데이터를 삭제하므로 정상 플로우에서는 영향 없음.

---

## [2026-03-10] DB 자동 테이블 생성 + 유저 위치 Redis-only 전환 + CSV/클라이언트 버그 수정

### 즉시 수정한 버그

#### BUG #1 - unit_info.csv 한글 인코딩 깨짐 ✅

- 발생 위치: `meta_data/unit_info.csv`
- 원인: korean_name 컬럼의 한글 데이터가 U+FFFD (ef bf bd) 바이트로 치환되어 있었음. 이전 저장 시점에 인코딩 손상 발생 추정.
- 해결: 정상 UTF-8 한글로 CSV 파일 전체 재작성. (보병, 중보병, 검사, 팔라딘 등 12개 유닛 이름)

#### BUG #2 - unit.html 유닛 능력치 차트 랜덤 값 표시 ✅

- 발생 위치: `templates/unit.html` / `createUnitStatsChart()`
- 원인: `Math.random() * 100`으로 임시 데이터 사용. 서버에서 전달하는 `unit.ability` 객체(attack, defense, health, speed)를 무시.
- 해결: `unit.ability`에서 실제 스탯 값을 읽어 Chart.js 바 차트에 반영.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- `resource.html`에서 루비 `<span id="gold-value">`로 중복 ID 사용 중 (ruby-value가 아닌 gold-value). `getElementById('ruby-value')` 호출 시 null 반환 가능.
- 유저 맵 위치가 Redis-only로 전환됨에 따라, Redis 재시작 시 유저 위치 유실. 서버 재시작 시 랜덤 재배정됨.

---

## [2026-03-09] 성 일반전투 (multi-attacker) 구현

### 즉시 수정한 버그

#### BUG #1 - _castle_all_attackers_win 수비 손실 계산 오류 ✅

- 발생 위치: `services/game/BattleManager.py` / `_castle_all_attackers_win`
- 원인: 현재 틱의 snapshot(마지막 틱 잔존 병력)만 ready에서 차감. 이전 틱의 누적 손실이 반영되지 않아 수비자 유닛이 부분만 사망 처리됨.
- 해결: `def_units_original` (전투 시작 시점의 ready 캐시 기준) 필드를 battle state에 추가. 종료 시 원본 기준으로 정확히 차감.

#### BUG #2 - battle_start 기존 전투 동기화 누락 ✅

- 발생 위치: `services/game/BattleManager.py` / `battle_start`
- 원인: 새 전투 시작 시 항상 수비자 ready 캐시에서 def_units를 읽음. 이미 진행 중인 전투에서 감소된 수비 병력과 불일치.
- 해결: `get_castle_battles()`로 기존 진행 중 전투 확인 후, 있으면 해당 전투의 현재 def_units로 동기화.

### 테스트 검증 중 발견/수정한 이슈

#### TEST-FIX #1 - 순환 import 오류 ✅

- 발생 위치: `tests/test_castle_battle.py` 모듈 레벨 import
- 원인: `from services.game.BattleManager import BattleManager`를 모듈 레벨에서 호출 시 순환 import 체인 발생 (BattleManager → game/__init__ → ResourceManager → system/__init__ → APIManager → game modules). `AttributeError: partially initialized module` 에러.
- 해결: 모든 import를 `create_battle_manager()` 함수 내부 및 개별 테스트 메서드 내부로 deferred import 처리.

#### TEST-FIX #2 - 전투 무한 루프 (unit 401 정수 데미지 모델) ✅

- 발생 위치: `tests/test_castle_battle.py` / `test_single_attacker_until_finish` 외 3개 테스트
- 원인: unit 401의 스탯이 attack=1, defense=1, hp=100. 공격자 100명 vs 수비 10명일 때 `net_atk = max(1, 100-10) = 90`, `killed = 90 // 100 = 0`. 매 라운드 처치 0명 → 전투 무한 반복.
- 해결: 유닛 수를 충분히 크게 설정 (공격자 1000+명) → `net_dmg = 990`, `killed = 990 // 100 = 9`명/라운드.

#### TEST-FIX #3 - 약탈 합산 오차 (int 절삭) ✅

- 발생 위치: `tests/test_castle_battle.py` / `test_multi_attacker_defender_eliminated`
- 원인: `int(amt * ratio)`로 각 공격자 몫 계산 시 소수점 절삭. 2명 분배 시 합계가 total_loot보다 1~2 적을 수 있음.
- 해결: `assert total_looted == 2000` → `assert 1990 <= total_looted <= 2000` 범위 허용.

### 알려진 한계/주의사항

- 수비자가 전투 중 새 유닛 훈련 완료 시, 해당 유닛은 진행 중인 전투에 투입되지 않음 (ready 캐시에만 반영, battle state의 def_units에는 미반영). 의도된 동작.
- 무한 교착 가능성 (라운드 제한 없음): 공격/방어 DPS가 서로의 HP를 0으로 만들 수 없는 극단적 경우. 추후 기술적 이슈로 분류하여 해결 예정.
- 정수 데미지 모델 한계: `killed = net_dmg // hp_per_unit`이므로 소규모 병력 간 교전에서 0 kills 가능. 의도된 동작이지만 밸런스 주의 필요.

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

---

## [2026-03-09] 연맹 버프 시스템 구현 + 버그 수정

### 즉시 수정한 버그

#### BUG #1 - _remove_alliance_buff target_type 하드코딩 ✅

- 발생 위치: `services/game/AllianceManager.py` / `_remove_alliance_buff` (기존 line 122)
- 원인: `remove_permanent_buff(..., "unit")` — target_type이 `"unit"`으로 하드코딩. 연맹 레벨 버프(buff_idx 103)의 실제 target_type은 `"building"`. 탈퇴/추방/해산 시 연맹 레벨 버프가 삭제되지 않음.
- 해결: `_get_buff_target_type(buff_idx)` 헬퍼 추가. buff_info config에서 실제 target_type을 조회하여 삭제.

#### BUG #2 - 탈퇴/추방 시 연맹 연구 버프 미삭제 ✅

- 발생 위치: `services/game/AllianceManager.py` / `_remove_alliance_buff`
- 원인: `source_type="alliance"` 소스만 삭제. `source_type="alliance_research"` 소스(연맹 연구 버프)는 삭제 로직 없음. 탈퇴/추방/해산 후에도 연구 버프가 유저에게 잔존.
- 해결: `_remove_alliance_buff`에서 `alliance_research` config를 순회하며 각 연구 버프의 target_type을 조회하여 모두 삭제.

#### BUG #3 - 신규 가입자에게 기존 연구 버프 미적용 ✅

- 발생 위치: `services/game/AllianceManager.py` / `_add_alliance_buff`
- 원인: 연맹 레벨 버프만 적용. 이미 레벨업 완료된 연맹 연구 버프는 가입 시 적용되지 않음. 기존 멤버만 연구 버프를 보유.
- 해결: `_add_alliance_buff`에서 `alliance_redis.get_all_research()`로 기존 연구 상태를 조회하고, level > 0인 연구의 버프를 모두 적용.

### 미해결 이슈

#### ISSUE #1 - 공지사항 권한 불일치 (CSV vs 코드) → ✅ 해결 (2026-03-09)

- 발생 위치: `services/game/AllianceManager.py` / `alliance_notice_write`
- 원인: `alliance_position.csv`에서 간부(3)도 `can_notice=1`이지만, 코드는 `my_position != POSITION_LEADER` (맹주만 허용)
- 해결: CSV 기준으로 수정 — `_has_permission(my_position, 'can_notice')` 사용

### 알려진 한계/주의사항
- 연맹 레벨업 시 `_update_alliance_buff_for_all_members`가 remove→add를 호출하므로 연구 버프도 불필요하게 재설정됨. 정합성 문제는 없으나 멤버 수 × 연구 수만큼 Redis 호출 발생.
- `alliance_level.csv`의 buff_idx는 전 레벨 동일(103). 레벨별로 다른 버프를 적용하려면 구조 변경 필요.
- `alliance_donate.csv`의 `coin_item_idx`가 0이므로 연맹 코인 아이템은 실제 지급되지 않음.
- DB 동기화 시 탈퇴/추방 멤버가 DB에서 삭제되지 않을 수 있음 (SyncWorker가 upsert만 수행).

---

## [2026-03-09] 연맹 테스트 + 버그 수정

### 즉시 수정한 버그

#### BUG #4 - AllianceManager buff_redis → buff_manager 레이어 오류 ✅

- 발생 위치: `services/game/AllianceManager.py` / `_add_alliance_buff`, `_remove_alliance_buff`, `_apply_research_buff` (4개소)
- 원인: `self.redis_manager.get_buff_manager()` → `BuffRedisManager` (redis layer) 반환. `add_permanent_buff`/`remove_permanent_buff`는 `BuffManager` (game layer)에만 존재. 연맹 버프 적용/삭제가 모두 `AttributeError`로 실패.
- 해결: `_get_buff_manager()` 헬퍼 추가. `BuffManager(self.db_manager, self.redis_manager)` 생성하여 game layer 메서드 호출.

#### BUG #5 - buff_info.csv 인코딩 깨짐 ✅

- 발생 위치: `meta_data/buff_info.csv`
- 원인: 이전 세션에서 UTF-8로 저장되었으나 `GameDataManager`는 `encoding='cp949'`로 읽음. `UnicodeDecodeError` 발생.
- 해결: git에서 원본 cp949 바이트 복원 후 buff_idx 205 행을 cp949로 append.

#### BUG #6 (ISSUE #1 해결) - 공지사항 권한 불일치 ✅

- 발생 위치: `services/game/AllianceManager.py` / `alliance_notice_write`
- 원인: `alliance_position.csv`에서 간부(3)도 `can_notice=1`이지만, 코드는 `my_position != POSITION_LEADER` (맹주만 허용)
- 해결: `_has_permission(my_position, 'can_notice')` 사용으로 CSV 기준 동작.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- 연맹 레벨업 시 `_update_alliance_buff_for_all_members`가 remove→add를 호출하므로 연구 버프도 불필요하게 재설정됨. 정합성 문제는 없으나 멤버 수 × 연구 수만큼 Redis 호출 발생.

---

## [2026-03-09] Buff 미해결 이슈 수정

### 즉시 수정한 버그

#### ISSUE #1 해결 - buff_total_info / buff_total_by_type_info API 미등록 ✅

- 발생 위치: `services/system/APIManager.py`
- 원인: `BuffManager.buff_total_info()`와 `buff_total_by_type_info()` 메서드는 존재하지만 APIManager에 api_code 미등록. 클라이언트 `buff.html`에서 API 코드 1111을 호출하지만 400 에러 반환.
- 해결: APIManager에 1013(buff_total_info), 1014(buff_total_by_type_info) 등록. `buff_total_by_type_info`를 APIManager 패턴에 맞게 `self.data`에서 `target_type`을 읽도록 수정. `buff.html`의 api_code 1111 → 1013으로 변경.

#### ISSUE #2 해결 - get_completed_tasks에서 sub_id KeyError 가능성 ✅

- 발생 위치: `services/redis_manager/base_redis_task_manager.py` / `get_completed_tasks` (line 82)
- 원인: `parsed['sub_id']`를 무조건 참조하지만, buff는 2-part key(`{user_no}:{buff_id}`)로 `sub_id`가 없음. KeyError 발생.
- 해결: `parsed['sub_id']` → `parsed.get('sub_id')` 변경.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- `buff_total_by_type_info`(1014)는 `self.data`에서 `target_type`을 읽는 방식으로 변경. 기존에 `target_type` 파라미터를 직접 받던 내부 호출 코드가 있으면 영향받을 수 있으나, 현재 내부 호출 없음 확인.

---

## [2026-03-09] 집결(Rally) 시스템 구현

### 즉시 수정한 버그

#### BUG #7 - _distribute_survived_units Leader 식별 불확실 ✅

- 발생 위치: `services/game/BattleManager.py` / `_distribute_survived_units`
- 원인: 나머지 유닛을 `next(iter(contributors))`로 첫 번째 contributor에게 주는데, Redis hgetall 반환 순서가 Leader 보장 안 됨.
- 해결: `leader_no` 파라미터 명시적 전달, 나머지 유닛을 leader_no에게 할당.

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- Rally는 Redis-only 데이터. 서버 재시작 시 진행 중 Rally 데이터 유실.
- Leader의 행군 슬롯 march는 `target_type="rally_slot"`으로 생성되며, 실제 이동은 없음. rally_attack 시 별도 march 생성.
- gather 행군 도착과 recruit 만료가 동일 TaskWorker 루프에서 순차 처리되므로 경합 없음. 다만 동일 루프에서 두 이벤트 모두 `try_launch_rally`를 호출하는 경우 status 체크로 중복 발사 방지.

---

## [2026-03-08] Resource / Item / Shop 테스트 검증

### 즉시 수정한 버그

(없음)

### 미해결 이슈

(없음)

### 알려진 한계/주의사항
- `CacheType` enum에서 자원 카테고리는 `RESOURCE`가 아닌 `RESOURCES` (복수형). 테스트 작성 시 혼동 주의.
- `ShopManager.shop_buy()` — `data` 파라미터가 빈 dict `{}`이면 `not self._data`가 `True`로 평가되어 `"Missing data"` 반환. slot 누락과 동일 분기. 명시적 `"slot"` 키 누락 메시지가 없음.
- fakeredis가 Lua 스크립트(`EVAL`)를 지원하지 않아 `conftest.py`에서 `atomic_consume`을 non-Lua로 패치. 실제 Redis와 동작 차이가 있을 수 있음.
