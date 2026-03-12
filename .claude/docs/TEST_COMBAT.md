# TEST_COMBAT.md - 전투 시스템 테스트 문서

> **프로젝트**: TheSeven
> **최종 수정**: 2026-03-12
> **테스트 파일**: `fastapi/tests/test_castle_battle.py` (기존), 추가 예정

---

## 1. 개요

### 1.1 테스트 범위

전투 시스템은 5개 핵심 모듈로 구성된다:

| 모듈 | 메서드 | 테스트 상태 |
|------|--------|------------|
| **성 일반전투** | `battle_start`, `process_castle_tick` | ✅ 17개 완료 |
| **NPC 전투** | `npc_battle_start`, `process_battle_tick`, `_npc_battle_end` | ✅ 21개 완료 |
| **NPC 집결 전투** | `rally_npc_battle_start`, `_rally_npc_battle_end`, `_distribute_survived_units` | ✅ 16개 완료 |
| **전투 계산 엔진** | `_calc_army_stats`, `calculate_round`, `_hero_coefficients`, `_check_rage_skill` | ✅ 28개 완료 |
| **API + 엣지케이스** | `battle_info`, `battle_report`, 동시성, 정합성 | ✅ 17개 완료 |

### 1.2 테스트 방식

```
BattleManager 메서드 직접 호출 (Worker 경유 아닌 단위 테스트)
  → DB session (theseven_test) + RedisManager(fakeredis) 로 인스턴스 생성
  → API 테스트는 AsyncClient + api_call 헬퍼 사용
```

### 1.3 테스트 인프라 특이사항

| 항목 | 내용 |
|------|------|
| DB | `theseven_test` MySQL, 테스트 간 DELETE 초기화 |
| Redis | `fakeredis` (인메모리), Lua 미지원 → `atomic_consume` non-Lua 패치 |
| Worker | 미실행 (BattleWorker/TaskWorker 비활성) |
| CSV | `GameDataManager.initialize()` 세션 1회 로드 |
| 전투 시작 | `battle_start()` 직접 호출 (TaskWorker 트리거 대신) |
| 틱 처리 | `process_battle_tick()` / `process_castle_tick()` 직접 호출 (BattleWorker 대신) |

---

## 2. 성 일반전투 (Castle Normal Attack) ✅

**테스트 파일**: `fastapi/tests/test_castle_battle.py`
**실행일**: 2026-03-12
**결과**: 17 passed

### 2.1 battle_start — 정상 전투 시작 (TestBattleStart)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_normal_battle_start` | 수비 병력 있는 상태 → 전투 시작, Redis state/active/castle_battle 생성 확인 | PASS |
| `test_already_processed_march` | march status=battling → 실패 | PASS |
| `test_no_march_metadata` | 존재하지 않는 march_id → 실패 | PASS |

### 2.2 battle_start — 무혈입성 (TestBloodlessEntry)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_bloodless_no_defender_units` | 수비 유닛 캐시 없음 → 무혈입성 + 약탈 20% + 자원 이전 확인 | PASS |
| `test_bloodless_zero_ready_units` | 수비 유닛 존재하나 ready=0 → 무혈입성 | PASS |

### 2.3 battle_start — 기존 전투 동기화 (TestExistingBattleSync)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_sync_def_units_from_existing_battle` | 기존 전투 수비 병력(60)으로 새 전투 def_units 동기화 | PASS |
| `test_bloodless_when_existing_battle_reduced_to_zero` | 기존 전투에서 수비 0 → 무혈입성 | PASS |

### 2.4 process_castle_tick — 단일 공격자 (TestCastleTickSingle)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_single_attacker_tick` | 1틱 진행 → round=1, state 업데이트 확인 | PASS |
| `test_single_attacker_until_finish` | 공격자 우세 → 수비 전멸까지 반복 틱 + Redis 정리 확인 | PASS |

### 2.5 process_castle_tick — 멀티 공격자 (TestCastleTickMulti)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_two_attackers_shared_snapshot` | 2명 공격 → 동일 수비 스냅샷 공유 확인 | PASS |
| `test_multi_attacker_defender_eliminated` | 수비 전멸 → 기여도(damage_dealt) 비율 약탈 분배, 수비 자원 감소 확인 | PASS |

### 2.6 process_castle_tick — 공격자 패배 (TestCastleTickAttackerLose)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_attacker_eliminated` | 공격자 전멸 → defender_win, march status=returning | PASS |
| `test_multi_one_attacker_dies_other_continues` | 약한 공격자 전멸 + 강한 공격자 생존 | PASS |

### 2.7 def_units_original 정합성 (TestDefUnitsOriginal)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_original_stored_at_battle_start` | ready 캐시 기준으로 def_units_original 저장 | PASS |
| `test_original_preserved_with_existing_battle` | 기존 전투 있어도 def_units_original은 ready 캐시 기준 | PASS |

### 2.8 calculate_round 단위 테스트 (TestCalculateRound)

| 테스트 | 목적 | 결과 |
|--------|------|------|
| `test_basic_round` | 양측 피해 발생, 결과 구조 확인 | PASS |
| `test_overwhelming_attack` | 압도적 공격 → 수비 전멸, 손실 검증 | PASS |

### 2.9 발견된 버그

없음.

### 2.10 미검증 항목 (성 일반전투)

| 항목 | 우선순위 | 비고 |
|------|---------|------|
| 수비자 유닛 death 카운트 증가 검증 | 중 | `_castle_all_attackers_win`에서 ready 차감 + death 증가 |
| 약탈 int 절삭 오차 검증 (1~2) | 낮 | `int(amt * ratio)` 절삭으로 합계 < 총 약탈량 |
| 전장(Battlefield) 내 전투 연동 | 중 | `bf_id` 설정 시 `bf_add_battle` / `bf_remove_battle` 호출 검증 |
| max_rounds 없음 무한 전투 방지 | 중 | 현재 라운드 제한 없음 → 동일 전력 교착 시 무한 루프 가능성 |

---

## 3. NPC 전투 ✅ 완료 (21 tests)

### 3.1 테스트 대상 메서드

| 메서드 | 책임 |
|--------|------|
| `npc_battle_start(march_id, npc_id)` | NPC 행군 도착 → 전투 시작 (NPC alive 체크, 영웅 계수 적용) |
| `process_battle_tick(battle_id)` | 1라운드 처리 (기력/스킬 포함, NPC/성 공통) |
| `_npc_battle_end(battle_id, ...)` | NPC 전투 종료 (EXP 지급, NPC alive=false, 리스폰 큐, 귀환 march) |

### 3.2 필수 테스트 케이스

#### npc_battle_start

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| N-01 | `test_npc_battle_start_normal` | 정상 NPC 전투 시작 | battle_type="npc", atk_units 일치, def_units=CSV 값, Redis state 생성, active battle 등록 |
| N-02 | `test_npc_battle_start_dead_npc` | NPC alive=false → 전투 없이 귀환 | success=false, march status=returning |
| N-03 | `test_npc_battle_start_no_march` | march 없음 → 실패 | success=false |
| N-04 | `test_npc_battle_start_already_processed` | march status≠marching → 실패 | success=false |
| N-05 | `test_npc_battle_start_invalid_npc` | 존재하지 않는 npc_id → 실패 | success=false |
| N-06 | `test_npc_battle_start_with_hero` | 영웅 동행 시 hero_coefficients 적용 | atk_max_hp에 영웅 계수 반영 |
| N-07 | `test_npc_battle_start_in_battlefield` | 전장 참여 상태에서 NPC 공격 | bf_id 설정, bf_add_battle 호출 확인 |

#### process_battle_tick (NPC용)

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| N-10 | `test_npc_tick_normal` | 1틱 진행 → round 증가, 양측 피해 | round=1, atk_units/def_units 변화 |
| N-11 | `test_npc_tick_attacker_win` | 공격자 승리 → _npc_battle_end 호출 | finished=true, result=attacker_win |
| N-12 | `test_npc_tick_attacker_lose` | 공격자 전멸 → defender_win | finished=true, result=defender_win |
| N-13 | `test_npc_tick_draw` | 양측 동시 전멸 → draw | finished=true, result=draw |
| N-14 | `test_npc_tick_rage_accumulation` | 매 틱 기력 누적 확인 | atk_rage += 25 (공격20+피격5), def_rage += 25 |
| N-15 | `test_npc_tick_skill_fire` | 기력 100 도달 → 스킬 발동, 킬 배율 증가 | skill_mult > 1.0, rage 리셋 |
| N-16 | `test_npc_tick_inactive_battle` | 비활성 전투 → 실패 | success=false |

#### _npc_battle_end

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| N-20 | `test_npc_end_exp_reward` | 승리 + 영웅 동행 → EXP 지급 | hero_dm.add_hero_exp 호출, hero 캐시 무효화 |
| N-21 | `test_npc_end_no_hero_no_exp` | 영웅 없이 승리 → EXP 미지급 | hero 관련 로직 스킵 |
| N-22 | `test_npc_end_npc_killed` | NPC 처치 → alive=false, 리스폰 큐 등록 | npc alive=false, completion_queue:npc_respawn 등록 |
| N-23 | `test_npc_end_return_march` | 귀환 march 생성 → status=returning, 귀환 큐 등록 | march metadata 업데이트, completion_queue:march_return 등록 |
| N-24 | `test_npc_end_db_finalize` | DB battle 결과 저장 | battle_dm.finalize_battle 호출, total_rounds/result 일치 |
| N-25 | `test_npc_end_redis_cleanup` | Redis 정리 → active battle 제거, status=finished | remove_active_battle, bf_remove_battle(전장 시) |
| N-26 | `test_npc_end_attacker_lose` | 공격자 패배 → NPC alive 유지, EXP 미지급 | npc alive=true, exp 미지급 |

---

## 4. NPC 집결 전투 (Rally NPC) ✅ 완료 (16 tests)

### 4.1 테스트 대상 메서드

| 메서드 | 책임 |
|--------|------|
| `rally_npc_battle_start(march_id, npc_id, rally_id)` | Rally attack 도착 → NPC 집결 전투 시작 (Leader 영웅만 적용) |
| `_rally_npc_battle_end(battle_id, ...)` | 전투 종료 → EXP 지급(Leader만) + 유닛 비율 분배 + 멤버별 개별 귀환 |
| `_distribute_survived_units(members, atk_alive, leader_no)` | 생존 유닛 → 원래 기여 비율로 floor 분배, 나머지 Leader에게 |

### 4.2 필수 테스트 케이스

#### rally_npc_battle_start

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| R-01 | `test_rally_npc_start_normal` | 정상 집결 전투 시작 | battle_type="rally_npc", rally_id 저장, Leader 영웅 적용 |
| R-02 | `test_rally_npc_start_dead_npc` | NPC dead → 실패 + march 귀환 | success=false, march status=returning |
| R-03 | `test_rally_npc_start_no_rally` | rally 정보 없음 → 실패 | success=false |
| R-04 | `test_rally_npc_start_already_processed` | march status≠marching → 실패 | success=false |

#### _rally_npc_battle_end

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| R-10 | `test_rally_npc_end_exp_leader_only` | 승리 → Leader 영웅에게만 EXP | leader hero exp 증가, 멤버 hero 무관 |
| R-11 | `test_rally_npc_end_npc_killed` | NPC alive=false, 리스폰 큐 등록 | 동일 NPC 전투 패턴 |
| R-12 | `test_rally_npc_end_member_return_marches` | 멤버별 개별 귀환 march 생성 | 각 멤버 march status=returning, 귀환 큐 등록 |
| R-13 | `test_rally_npc_end_attack_march_deleted` | attack march 정리 | delete_march_metadata(march_id) |
| R-14 | `test_rally_npc_end_rally_status_done` | rally status=done으로 업데이트 | combat_rm.update_rally 확인 |

#### _distribute_survived_units

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| D-01 | `test_distribute_proportional` | 2명(A:60, B:40) → 생존 50 → A:30, B:20 | floor division 정확성 |
| D-02 | `test_distribute_remainder_to_leader` | 나머지 유닛 → Leader에게 | leader에 +remainder |
| D-03 | `test_distribute_one_type_eliminated` | 특정 유닛 전멸(생존 0) → 해당 유닛 분배 없음 | 전멸 유닛 결과에 없음 |
| D-04 | `test_distribute_empty_members` | 멤버 없음 → 빈 결과 | {} 반환 |
| D-05 | `test_distribute_mixed_unit_types` | 보병+기병 혼합 → 유닛 타입별 독립 분배 | 각 unit_idx별 비율 분배 |
| D-06 | `test_distribute_single_member` | 1명만 참여 → 전체 생존 유닛 수령 | 그대로 반환 |

---

## 5. 전투 계산 엔진 ✅ 완료 (28 tests)

### 5.1 테스트 대상 메서드

| 메서드 | 책임 | 테스트 상태 |
|--------|------|------------|
| `_calc_army_stats(units, hero_coeffs)` | RoK 스타일 전투력 계산 (√count × stat × hero_coeff) | ⬜ 미작성 |
| `calculate_round(atk_stats, def_stats, ...)` | 1라운드 킬 수 계산 + 저티어 우선 제거 | 🔶 2개 존재 |
| `_hero_coefficients(hero_idx)` | CSV base_stat/100 → 배율 변환 | ⬜ 미작성 |
| `_get_hero_skill(hero_idx)` | hero_skill.csv에서 스킬 조회 | ⬜ 미작성 |
| `_check_rage_skill(rage, hero_idx)` | 기력 100 도달 → 스킬 발동 판정 | ⬜ 미작성 |

### 5.2 필수 테스트 케이스

#### _calc_army_stats

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| E-01 | `test_army_stats_basic` | 단일 유닛 타입 전투력 계산 | power = unit_atk × √count, defense/health 동일 패턴 |
| E-02 | `test_army_stats_mixed_units` | 보병+기병+궁병 혼합 | 각 유닛별 개별 계산 후 합산 |
| E-03 | `test_army_stats_with_hero` | 영웅 계수 적용 | power × hero_atk, defense × hero_def, health × hero_hp |
| E-04 | `test_army_stats_zero_count` | count=0 유닛 → 무시 | alive_units에서 제외 |
| E-05 | `test_army_stats_empty` | 유닛 없음 → 0 | power=0, defense=0, health=0 |

#### calculate_round (추가 필요)

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| E-10 | `test_round_low_tier_dies_first` | 보병(401)+기사(403) → 401 먼저 사망 | sorted(unit_idx) 순서대로 제거 |
| E-11 | `test_round_skill_mult_increases_kills` | skill_mult=1.5 → 킬 수 1.5배 | def_loss 증가 |
| E-12 | `test_round_both_skill_mult` | 양측 스킬 발동 → 양측 킬 증가 | atk_loss + def_loss 모두 증가 |
| E-13 | `test_round_equal_forces` | 동일 전력 → 양측 동일 피해 | atk_loss ≈ def_loss |
| E-14 | `test_round_zero_defense` | 방어력 0 → 킬 0 (division by zero 방지) | def_loss = 0 (방어측 방어=0이면 calc_kills=0) |

#### _hero_coefficients

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| E-20 | `test_hero_coeff_normal` | hero_idx 존재 → CSV 값/100 | base_attack=110 → atk=1.1 |
| E-21 | `test_hero_coeff_no_hero` | hero_idx=None → 기본값 1.0 | {atk: 1.0, def: 1.0, hp: 1.0} |
| E-22 | `test_hero_coeff_invalid_hero` | 존재하지 않는 hero_idx → 기본값 | {atk: 1.0, def: 1.0, hp: 1.0} |

#### _check_rage_skill

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| E-30 | `test_rage_below_max` | rage=80 → 스킬 미발동 | skill_mult=1.0, skill_fired=False |
| E-31 | `test_rage_at_max` | rage=100 + hero → 스킬 발동 | skill_mult>1.0, skill_fired=True, rage 리셋 |
| E-32 | `test_rage_no_hero` | rage=100 + hero=None → 스킬 미발동 | skill_mult=1.0 |
| E-33 | `test_rage_hero_no_skill` | rage=100 + hero 있지만 스킬 없음 → 미발동 | skill_mult=1.0 |
| E-34 | `test_rage_overflow` | rage=120 → 스킬 발동 후 rage=20 | rage -= 100 |

---

## 6. API 테스트 + 엣지케이스 ✅ 완료 (17 tests)

### 6.1 테스트 대상

| API 코드 | 메서드 | 설명 |
|----------|--------|------|
| 9021 | `battle_info` | 진행 중 전투 상태 조회 (Redis → DB 폴백) |
| 9022 | `battle_report` | 전투 보고서 목록 (DB) |

### 6.2 필수 테스트 케이스

#### battle_info (9021)

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| A-01 | `test_battle_info_active` | 진행 중 전투 → Redis 데이터 반환 | success=true, state 전체 |
| A-02 | `test_battle_info_finished_from_db` | 종료 전투 → DB 폴백 | success=true, DB battle 데이터 |
| A-03 | `test_battle_info_not_found` | 존재하지 않는 battle_id → 실패 | success=false, "전투 없음" |
| A-04 | `test_battle_info_no_permission` | 다른 유저의 전투 조회 → 권한 없음 | success=false, "권한 없음" |
| A-05 | `test_battle_info_missing_battle_id` | battle_id 누락 → 실패 | success=false |

#### battle_report (9022)

| ID | 테스트 | 목적 | 검증 포인트 |
|----|--------|------|------------|
| A-10 | `test_battle_report_empty` | 전투 이력 없음 → 빈 리스트 | reports=[] |
| A-11 | `test_battle_report_with_data` | 전투 종료 후 → 보고서 포함 | reports에 해당 전투 포함 |
| A-12 | `test_battle_report_limit` | limit=5 → 최대 5건 | len(reports) <= 5 |

---

## 7. 엣지케이스 & 동시성 시나리오

### 7.1 데이터 경계

| ID | 시나리오 | 검증 포인트 | 우선순위 |
|----|---------|------------|---------|
| EC-01 | 공격자 병력 1명 vs 수비 1명 | 1라운드에 양측 전멸 → draw | 중 |
| EC-02 | 공격자 병력 0명 (엣지) | battle_start 시점 검증 필요 | 중 |
| EC-03 | 수비자 Redis 유닛 캐시 없음 (최초 접근) | DB 폴백 or 빈 dict 처리 | 높 |
| EC-04 | NPC units 빈 dict (CSV 설정 오류) | 무혈입성 또는 에러 처리 | 중 |
| EC-05 | hero_idx가 문자열로 전달 | int 변환 안전성 | 낮 |

### 7.2 동시성 (Worker 경합)

| ID | 시나리오 | 검증 포인트 | 우선순위 |
|----|---------|------------|---------|
| CC-01 | 같은 march_id로 battle_start 2회 호출 | 두 번째 호출 실패 (status≠marching) | 높 |
| CC-02 | 전투 종료 직후 process_tick 호출 | status≠active → 실패 반환 | 높 |
| CC-03 | 멀티 공격자: 한 전투 종료 중 다른 전투 tick | castle_battle Set에서 제거된 bid 처리 | 중 |
| CC-04 | NPC 리스폰 중 동시 공격 | alive=false 체크 → 전투 거부 | 중 |

### 7.3 정합성

| ID | 시나리오 | 검증 포인트 | 우선순위 |
|----|---------|------------|---------|
| IC-01 | NPC 전투 종료 후 NPC alive 상태 | attacker_win → alive=false, defender_win → alive=true | 높 |
| IC-02 | 전투 종료 후 active_battle Set 정리 | remove_active_battle 호출 확인 | 높 |
| IC-03 | 전장 내 전투 종료 후 bf_battles Set 정리 | bf_remove_battle 호출 확인 | 중 |
| IC-04 | 수비자 유닛 death 카운트 정합성 | ready 차감 = death 증가 | 높 |
| IC-05 | 약탈 후 양측 자원 합산 보존 | 공격자 증가 + 수비자 감소 = 0 (절삭 오차 제외) | 높 |
| IC-06 | Rally 유닛 분배 합산 = 생존 유닛 | Σ(member_survived) = atk_alive | 높 |

---

## 8. 테스트 헬퍼 함수

`test_castle_battle.py`에 이미 정의된 헬퍼:

```python
setup_resources(fake_redis, user_no, food, wood, stone, gold)  # Redis 자원 세팅
setup_unit_cache(fake_redis, user_no, unit_idx, ready, field, death)  # Redis 유닛 캐시
setup_march(fake_redis, march_id, attacker_no, defender_no, units, hero_idx, status)  # March 메타데이터
setup_map_position(fake_redis, user_no, x, y)  # 맵 위치
create_battle_manager(db_session, fake_redis)  # BattleManager 인스턴스
```

### 추가 필요 헬퍼

```python
# NPC 테스트용
setup_npc_instance(fake_redis, npc_id, alive=True)  # Redis NPC 인스턴스 세팅
setup_hero_cache(fake_redis, user_no, hero_idx, hero_lv)  # Redis 영웅 캐시 세팅

# Rally 테스트용
setup_rally(fake_redis, rally_id, leader_no, npc_id, hero_idx, status)  # Rally 메타데이터
setup_rally_member(fake_redis, rally_id, user_no, units, march_id)  # Rally 멤버
```

---

## 9. Worker 통합 테스트 ⬜ 후속 진행

> **시점**: Worker 로직 변경 시, 또는 단위 테스트 Phase 1~5 완료 후
> **이유**: 단위 테스트는 BattleManager 메서드를 직접 호출하지만, 실제 서비스에서는
>          TaskWorker → BattleManager → BattleWorker → WebSocket 순서로 연쇄 호출된다.
>          이 연쇄 흐름에서만 발생하는 버그(트리거 누락, 상태 불일치)를 잡기 위한 테스트.

### 9.1 테스트 인프라 요구사항

현재 conftest.py는 `app.router.on_startup.clear()`로 Worker를 비활성화한다.
통합 테스트에서는 Worker를 직접 인스턴스화하되, `check_interval`을 수동 제어한다.

```python
# 통합 테스트용 Worker 인스턴스 (자동 루프 아닌 수동 1회 실행)
battle_worker = BattleWorker(redis_manager, ws_manager=mock_ws, check_interval=999)
task_worker = TaskWorker(redis_manager, ws_manager=mock_ws, check_interval=999)

# 수동 1회 실행
await task_worker._process_pending()   # march 도착 → battle_start 트리거
await battle_worker._process_pending() # 활성 전투 1틱 처리
```

### 9.2 테스트 대상 흐름

#### TaskWorker → BattleManager 연쇄

| ID | 흐름 | 검증 포인트 |
|----|------|------------|
| W-01 | **NPC march 도착 → npc_battle_start** | completion_queue:march에서 march_id 꺼냄 → target_type="npc" 분기 → npc_battle_start 호출 → battle:active 등록 |
| W-02 | **User march 도착 → battle_start** | target_type 미지정(default "user") → battle_start 호출 → 무혈입성/전투 시작 분기 |
| W-03 | **Rally gather 도착 → 멤버 arrived** | target_type="rally_gather" → member status=arrived → try_launch_rally 호출 |
| W-04 | **Rally attack 도착 → rally_npc_battle_start** | target_type="rally_attack" → rally_npc_battle_start 호출 |
| W-05 | **March 귀환 → 유닛 field→ready 복구** | completion_queue:march_return에서 감지 → _restore_units_on_return → metadata/큐 정리 |
| W-06 | **NPC 리스폰** | completion_queue:npc_respawn → NPC alive=true 복구 |

#### BattleWorker 연쇄

| ID | 흐름 | 검증 포인트 |
|----|------|------------|
| W-10 | **NPC 전투 틱 처리** | battle:active에서 npc 타입 감지 → process_battle_tick 호출 → 결과에 따라 종료 처리 |
| W-11 | **성 전투 그룹 틱 처리** | user 타입을 defender_no별 그룹화 → process_castle_tick 일괄 호출 |
| W-12 | **Rally NPC 전투 틱** | rally_npc 타입 → process_battle_tick → _rally_npc_battle_end 연쇄 |
| W-13 | **전장 집계 틱** | _send_battlefield_ticks → bf 1~3 각각 battle 상태 집계 → battlefield_tick JSON 생성 |

#### End-to-End 흐름

| ID | 흐름 | 검증 포인트 |
|----|------|------------|
| W-20 | **NPC 공격 전체 흐름** | march 생성 → (TaskWorker) 도착 → 전투 시작 → (BattleWorker) 틱 반복 → 전투 종료 → (TaskWorker) 귀환 → 유닛 복구 |
| W-21 | **성 공격 전체 흐름** | march 생성 → 도착 → 전투/무혈입성 → 틱 → 종료 → 약탈 → 귀환 → 유닛 복구 |
| W-22 | **Rally NPC 전체 흐름** | rally 생성 → gather march → (도착) → launch → rally_attack march → (도착) → 전투 → 종료 → 유닛 분배 → 멤버별 귀환 |

### 9.3 테스트 방식

```python
class TestNpcBattleE2E:
    """NPC 공격 End-to-End: march → battle → return"""

    async def test_full_npc_flow(self, battle_env):
        # 1. March 생성 + completion_queue 등록 (시간 과거로)
        await setup_march(fr, 1, ATTACKER_NO, 0, {401: 100},
                          status="marching", target_type="npc", npc_id=101)
        await combat_rm.add_march_to_queue(1, datetime.utcnow() - timedelta(seconds=1))

        # 2. TaskWorker 1회 실행 → march 도착 → npc_battle_start
        await task_worker._process_pending()
        active = await combat_rm.get_active_battles()
        assert len(active) == 1  # 전투 시작됨

        # 3. BattleWorker N회 실행 → 전투 종료까지
        for _ in range(50):
            await battle_worker._process_pending()
            active = await combat_rm.get_active_battles()
            if not active:
                break
        assert not active  # 전투 종료됨

        # 4. TaskWorker 1회 실행 → 귀환 도착 처리 (시간 조작)
        # ... 귀환 시간을 과거로 설정 후 _process_pending
        # 5. 유닛 복구 확인
```

### 9.4 주의사항

| 항목 | 내용 |
|------|------|
| DB 세션 관리 | Worker가 내부에서 `SessionLocal()` 호출 → 테스트에서는 `_create_db_session`을 패치하여 theseven_test 세션 반환 |
| WebSocket mock | `websocket_manager`에 mock 객체 전달. `send_personal_message` / `broadcast_message` 호출 기록만 수집 |
| 시간 조작 | `completion_queue` score를 과거 timestamp로 설정하여 즉시 처리 유도 |
| Worker 루프 제어 | `_process_pending()`를 직접 호출. `run()` 루프는 사용하지 않음 |

---

## 10. WebSocket 이벤트 검증 ⬜ 후속 진행

> **시점**: 클라이언트 연동 이슈 발생 시, 또는 Worker 통합 테스트와 함께
> **이유**: 전투 상태 변경 시 올바른 수신자에게 올바른 이벤트가 전달되는지 검증.
>          현재 테스트 인프라에 WebSocket mock이 없으므로 별도 구축 필요.

### 10.1 테스트 인프라 요구사항

```python
class MockWebSocketManager:
    """WebSocket 이벤트 수집용 mock"""

    def __init__(self):
        self.personal_messages = []   # [(user_no, message_str), ...]
        self.broadcast_messages = []  # [message_dict, ...]

    async def send_personal_message(self, message: str, user_no: int):
        self.personal_messages.append((user_no, json.loads(message)))

    async def broadcast_message(self, message: dict):
        self.broadcast_messages.append(message)

    def get_messages_for(self, user_no: int, msg_type: str = None):
        """특정 유저가 받은 메시지 필터"""
        msgs = [m for no, m in self.personal_messages if no == user_no]
        if msg_type:
            msgs = [m for m in msgs if m.get("type") == msg_type]
        return msgs

    def get_broadcasts(self, msg_type: str = None):
        if msg_type:
            return [m for m in self.broadcast_messages if m.get("type") == msg_type]
        return self.broadcast_messages
```

### 10.2 이벤트별 검증 매트릭스

#### BattleWorker → 전투 참여자

| ID | 이벤트 | 트리거 | 수신자 | 검증 포인트 |
|----|--------|--------|--------|------------|
| WS-01 | `battle_tick` | 매 틱 (ongoing) | 공격자, 수비자, 관전자 | battle_id, round, atk_units, def_units 포함 |
| WS-02 | `battle_end` | 전투 종료 | 공격자, 수비자, 관전자 | battle_id, result 포함 |
| WS-03 | `battle_end` 후 구독 정리 | 전투 종료 | - | `clear_battle_subscribers` 호출 확인 |

#### TaskWorker → 전투 시작 알림

| ID | 이벤트 | 트리거 | 수신자 | 검증 포인트 |
|----|--------|--------|--------|------------|
| WS-10 | `battle_start` | NPC march 도착 | 공격자 | atk_user_no, battle_type="npc", battle_id |
| WS-11 | `battle_start` | User march 도착 | 공격자 + 수비자 | 양측 모두 수신 |
| WS-12 | `battle_incoming` | User march 도착 | 수비자만 | battle_id (경고 알림) |
| WS-13 | `battle_bloodless` | 무혈입성 | 공격자 | loot 데이터 포함 |
| WS-14 | `battle_bloodless_defend` | 무혈입성 | 수비자 | 약탈당한 사실 알림 |
| WS-15 | `battle_start` | Rally attack 도착 | 전체 rally 멤버 | rally_id 포함 |

#### 맵 브로드캐스트

| ID | 이벤트 | 트리거 | 수신자 | 검증 포인트 |
|----|--------|--------|--------|------------|
| WS-20 | `map_march_update` | 전투 시작 | 전체 | status="battling" |
| WS-21 | `map_march_update` | 전투 종료 → 귀환 | 전체 | status="returning", return_time |
| WS-22 | `map_march_complete` | 귀환 완료 | 전체 | march_id |

#### 전장 틱

| ID | 이벤트 | 트리거 | 수신자 | 검증 포인트 |
|----|--------|--------|--------|------------|
| WS-30 | `battlefield_tick` | BattleWorker 매 틱 | bf 구독자 | bf_id, battles 배열 (battle_id, x, y, hp_pct, round) |
| WS-31 | `battlefield_tick` 빈 전투 | bf 내 전투 0건 | - | 틱 미전송 (전투 없으면 스킵) |
| WS-32 | `battlefield_tick` 종료 전투 정리 | bf_battles에 finished 전투 | - | bf_remove_battle 호출 후 배열에서 제외 |

#### Rally NPC 알림 분배

| ID | 이벤트 | 트리거 | 수신자 | 검증 포인트 |
|----|--------|--------|--------|------------|
| WS-40 | `battle_tick` | Rally NPC 틱 | rally 전체 멤버 | 개별 전투와 달리 rally_members 전원에게 |
| WS-41 | `battle_end` | Rally NPC 종료 | rally 전체 멤버 + 관전자 | result 포함 |

### 10.3 수신자 정확성 핵심 테스트

```python
class TestBattleWSRecipients:
    """올바른 수신자에게만 이벤트가 전달되는지 검증"""

    async def test_npc_tick_only_attacker(self, ...):
        """NPC 전투 tick → 공격자만 수신 (수비자=NPC이므로 0)"""
        # BattleWorker 1회 실행
        # mock_ws에서 공격자만 battle_tick 수신 확인
        # defender_no=0이므로 수비자 알림 없음

    async def test_castle_tick_both_sides(self, ...):
        """성 전투 tick → 공격자 + 수비자 모두 수신"""
        # 양측 모두 battle_tick 수신 확인

    async def test_spectator_receives_tick(self, ...):
        """관전자 → battle_tick 수신"""
        # battle_subscribers에 관전자 등록 후
        # BattleWorker 1회 → 관전자도 tick 수신

    async def test_third_party_no_tick(self, ...):
        """비관련 유저 → tick 미수신"""
        # 전투 미참여 + 미관전 유저는 메시지 0건
```

---

## 11. 성능 벤치마크 ⬜ 후속 진행

> **시점**: C++ 포팅 시점, 또는 동시 전투 수가 50+로 증가할 때
> **이유**: BattleWorker는 1초 주기로 모든 활성 전투를 처리해야 한다.
>          Python `calculate_round`의 처리 한계를 측정하고, C++ 포팅 후 비교 벤치마크 수행.

### 11.1 벤치마크 시나리오

| ID | 시나리오 | 측정 대상 | 기대 임계값 |
|----|---------|-----------|------------|
| P-01 | **단일 전투 1틱** | `process_battle_tick` 1회 실행 시간 | < 1ms |
| P-02 | **N개 NPC 전투 동시 틱** | `_process_pending` (N개 individual_battles) | N=100: < 500ms |
| P-03 | **성 전투 M명 공격자** | `process_castle_tick(defender, [M개 bids])` | M=10: < 100ms |
| P-04 | **calculate_round 순수 계산** | 함수 호출 10,000회 | < 1초 |
| P-05 | **전장 집계 틱** | `_send_battlefield_ticks` (3개 전장, 각 50전투) | < 200ms |

### 11.2 벤치마크 방법

```python
# pytest-benchmark 또는 수동 측정
import time

class TestBattlePerformance:
    """성능 측정 (pytest -k performance --no-header)"""

    async def test_single_tick_latency(self, battle_env):
        """단일 NPC 전투 1틱 처리 시간"""
        # setup: NPC 전투 1개 시작
        start = time.perf_counter()
        for _ in range(1000):
            await env["bm"].process_battle_tick(battle_id)
        elapsed = time.perf_counter() - start
        avg_ms = elapsed / 1000 * 1000
        print(f"Average tick: {avg_ms:.3f}ms")
        assert avg_ms < 5.0  # 5ms 이하

    async def test_concurrent_battles_throughput(self, battle_env):
        """N개 동시 전투 처리량"""
        N = 100
        # setup: N개 NPC 전투 시작
        start = time.perf_counter()
        for bid in battle_ids:
            await env["bm"].process_battle_tick(bid)
        elapsed = time.perf_counter() - start
        print(f"{N} battles: {elapsed*1000:.1f}ms")
        assert elapsed < 1.0  # 1초 이내

    def test_calculate_round_raw(self, load_game_data):
        """calculate_round 순수 계산 성능"""
        from services.game.BattleManager import BattleManager
        atk = {"power": 500, "defense": 200, "health": 5000, "alive_units": {401: 50}}
        def_ = {"power": 300, "defense": 100, "health": 3000, "alive_units": {401: 30}}
        start = time.perf_counter()
        for _ in range(10000):
            BattleManager.calculate_round(atk, def_)
        elapsed = time.perf_counter() - start
        print(f"10K rounds: {elapsed*1000:.1f}ms")
        assert elapsed < 2.0
```

### 11.3 병목 예상 지점

| 지점 | 원인 | 대응 |
|------|------|------|
| `get_battle_state` N회 호출 | 전투당 Redis HGETALL 1회 | Pipeline/MGET 배치 조회 |
| `set_battle_state` N회 호출 | 전투당 Redis HSET 1회 | Pipeline 배치 쓰기 |
| `calculate_round` 계산량 | Python 루프 (dict 순회, sqrt) | C++ pybind11 포팅 |
| `_send_battlefield_ticks` | 전장당 전투 수 × 구독자 수 WS 전송 | 구독자 수 제한 or 배치 전송 |

### 11.4 C++ 포팅 비교 기준

```
현재 Python 기준 측정 → C++ 포팅 후 동일 시나리오 재측정

목표:
  P-02 (100 전투): Python < 500ms → C++ < 50ms (10x)
  P-04 (10K 라운드): Python < 2s → C++ < 100ms (20x)

포팅 대상: calculate_round() + _calc_army_stats()
인터페이스: pybind11, 동일 입출력 Dict 구조
```

---

## 12. 구현 우선순위

```
┌─────────────────────────────────────────────────────────────────┐
│ 즉시 진행 (단위 테스트)                                           │
│                                                                   │
│  Phase 1: NPC 전투 (N-01~N-26)            ← 최우선                │
│  Phase 2: 전투 계산 엔진 보강 (E-01~E-34)                          │
│  Phase 3: NPC 집결 전투 (R-01~R-14, D-01~D-06)                    │
│  Phase 4: API 테스트 (A-01~A-12)                                  │
│  Phase 5: 엣지케이스 & 정합성 (EC/CC/IC)                           │
├─────────────────────────────────────────────────────────────────┤
│ 후속 진행                                                         │
│                                                                   │
│  Phase 6: Worker 통합 테스트 (W-01~W-22)  ← Worker 로직 변경 시   │
│  Phase 7: WebSocket 이벤트 검증 (WS-01~WS-41) ← 클라이언트 연동 시│
│  Phase 8: 성능 벤치마크 (P-01~P-05)       ← C++ 포팅 시           │
└─────────────────────────────────────────────────────────────────┘
```

| Phase | 테스트 수 | 트리거 조건 |
|-------|----------|------------|
| 1~5 | 약 70개 | **즉시** (compact 후 구현) |
| 6 | 약 15개 | Worker 로직 변경 or Phase 1~5 완료 후 |
| 7 | 약 20개 | 클라이언트 연동 이슈 발생 시 |
| 8 | 5개 | C++ 포팅 시작 시 |

---

## 13. 참고

- 전투 시스템 설계: `.claude/docs/COMBAT.md`
- 기존 성 전투 테스트: `fastapi/tests/test_castle_battle.py`
- BattleManager 구현: `fastapi/services/game/BattleManager.py`
- CombatRedisManager: `fastapi/services/redis_manager/combat_redis_manager.py`
- BattleWorker: `fastapi/services/background_workers/battle_worker.py`
- TaskWorker: `fastapi/services/background_workers/task_worker.py`
- WebsocketManager: `fastapi/services/system/WebsocketManager.py`
- 테스트 인프라: `fastapi/tests/conftest.py`
