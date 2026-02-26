# 이슈 추적

## 발견일: 2026-02-26 (전체 API E2E 테스트)

테스트 환경: `user_no: 10017`, 서버 `localhost:8000`

---

## 버그 (코드 수정 필요)

### BUG-001 | 2005 - 건물 건설/업그레이드 취소
- **증상**: `success: false, message: "Building cancel failed: 'BuildingRedisManager' object has no attribute 'delete_cached_building'"`
- **원인**: `BuildingManager.building_cancel()`에서 `delete_cached_building()` 호출 → `BuildingRedisManager`의 실제 메서드명은 `remove_cached_building()`
- **수정 파일**: `services/game/BuildingManager.py:785`
- **수정 내용**: `building_redis.delete_cached_building(...)` → `building_redis.remove_cached_building(...)`
- **상태**: ✅ 수정 완료

---

### BUG-002 | 3004 - 연구 취소
- **증상**: `success: false, message: "Error cancelling research: 'cost'"`
- **원인**: `research_cancel()`에서 config 구조 오해. `REQUIRE_CONFIGS['research'][idx]`는 `{lv: {cost, time}}` 중첩 구조인데 `config['cost']`로 직접 접근
- **수정 파일**: `services/game/ResearchManager.py`
- **수정 내용** (3건):
  1. **713-714행**: config 구조 오해 수정 — `config['cost']` → `target_lv = research_lv+1` 계산 후 `config.get(target_lv, {}).get('cost', {})`
  2. **721행**: `add_resources(user_no, dict)` → `for resource_type, amount in ... : add_resource(user_no, resource_type, amount)` (메서드명/호출방식 불일치)
  3. **726행**: `update_research_status(user_no, research_idx, STATUS_AVAILABLE)` → `update_research_status(user_no, research_idx, status=STATUS_AVAILABLE)` (`**kwargs` 방식 메서드에 positional 전달 오류)
- **상태**: ✅ 수정 완료

---

### BUG-003 | 연맹 권한 기반 API 전체 (7007~7010, 7012~7013, 7015)
- **증상**: `success: false, message: "xxx 권한이 없습니다"` — 리더(맹주)로 요청해도 실패
- **근본 원인**: `meta_data/` 폴더에 `alliance_position.csv` 파일이 없음
  - `AllianceManager._get_position_config()` → 빈 dict 반환
  - `AllianceManager._has_permission()` → 항상 `False` 반환
- **수정 내용** (3건):
  1. `meta_data/alliance_position.csv` 생성 — position 1~4별 권한 정의
  2. `meta_data/alliance_level.csv` 생성 — 레벨별 max_members, required_exp
  3. `GameDataManager.py` — `REQUIRE_CONFIGS`에 alliance 키 추가 + 로딩 메서드 4개 추가
  - 추가 수정: `AllianceManager.alliance_notice_write()` 파라미터명 `content` → `notice` (7015)
- **상태**: ✅ 수정 완료

---

### BUG-004 | 7011 - 연맹 경험치 기부
- **증상**: `success: false, message: "기부할 수 없는 자원입니다"`
- **근본 원인**: `meta_data/` 폴더에 `alliance_donate.csv` 파일이 없음
  - `AllianceManager._get_donate_config()` → 빈 dict 반환
- **수정 내용** (3건):
  1. `meta_data/alliance_donate.csv` 생성 — food/wood/stone/gold/ruby별 exp_ratio, coin_ratio 정의
  2. `AllianceManager.py:726` import 경로 수정 — `services.resource.ResourceManager` → `services.game.ResourceManager`
  3. `AllianceManager.py:729` 메서드명 수정 — `atomic_consume(user_no, type, amount, label)` → `consume_resources(user_no, {type: amount})`
- **상태**: ✅ 수정 완료

---

### BUG-005 | 7017 - 연맹 연구 진행
- **증상**: `success: false, message: "존재하지 않는 연구입니다"`
- **근본 원인**: 연맹 연구 config CSV 미존재 (alliance_research 계열 CSV 없음)
- **수정 내용**: `meta_data/alliance_research.csv` 생성 — research_idx 8001~8003, 레벨 1~5 정의
- **상태**: ✅ 수정 완료

---

## API.md 명세 오류 (수정 완료)

아래 항목은 실제 구현과 API.md 명세가 불일치하여 API.md를 실제 구현 기준으로 수정함.

| API | 항목 | 기존 명세 (오류) | 실제 구현 (정상) |
|-----|------|----------------|----------------|
| 3002 | 파라미터 | `research_idx` 만 | `research_idx` + `research_lv` 필수 |
| 4002 | 파라미터명 | `count` | `quantity` |
| 4003 | 파라미터 | `unit_idx` 만 | `unit_idx` + `target_unit_idx` + `quantity` 필수 |
| 6013 | 파라미터 | `item_idx` | `slot` (슬롯 번호 int) |
| 7002 | 파라미터명 | `alliance_name` | `name` |
| 7003 | 파라미터명 | `alliance_id` | `alliance_no` |
| 7008 | 파라미터 | `new_role: "officer"` (string) | `new_position: 3` (int, 1~4) |
| 7011 | 파라미터 | `amount` 만 | `resource_type` + `amount` 필수 |
| 7012 | 파라미터 타입 | `join_type: 0` (int) | `join_type: "free"/"approval"` (string) |

---

## 기타 주의사항

### ~~WARN-001~~ | /health 엔드포인트 오류 ✅ 수정 완료
- **증상**: `{"status":"error","message":"type object 'GameDataManager' has no attribute 'is_initialized'"}`
- **원인**: `GameDataManager`에 `is_initialized` 속성 없음. 헬스체크 라우터에서 참조 중
- **수정**: `main.py` — `GameDataManager.is_initialized()` → `GameDataManager._loaded`

### WARN-002 | 건물 인덱스 101 config 없음
- **증상**: 2002 호출 시 `"Building 101 config not found"`
- **원인**: `building_info.csv`에 `building_idx=101` 데이터 없음
- **영향**: API.md에 명시된 건물 인덱스 `101, 201, 301, 401` 중 101 사용 불가

### WARN-003 | 아이템 인덱스 1001 config 없음
- **증상**: 6003 호출 시 `"Failed to apply item effect: Item 1001 config not found"`
- **원인**: `item_info.csv`에 `item_idx=1001` 없거나 포맷 불일치
- **영향**: API.md 예시 값으로 직접 테스트 불가

### WARN-004 | 5002 보상 응답에 지급 내역 없음
- **증상**: 미션 보상 수령 성공 시 응답에 실제 지급된 아이템/자원 정보 없음
- **영향**: 클라이언트가 수령 결과를 알 수 없음 (UX 문제)

---

## 수정 우선순위

| 우선순위 | 이슈 | 이유 |
|---------|------|------|
| ~~P1~~ | ~~BUG-003 (alliance_position.csv 생성)~~ | ✅ 수정 완료 |
| ~~P1~~ | ~~BUG-004 (alliance_donate.csv 생성)~~ | ✅ 수정 완료 |
| ~~P2~~ | ~~BUG-002 (3004 연구 취소 KeyError)~~ | ✅ 수정 완료 |
| ~~P2~~ | ~~BUG-001 (2005 건물 취소 메서드 없음)~~ | ✅ 수정 완료 |
| ~~P3~~ | ~~BUG-005 (alliance_research.csv 생성)~~ | ✅ 수정 완료 |
| ~~P3~~ | ~~WARN-001 (health 엔드포인트)~~ | ✅ 수정 완료 |
