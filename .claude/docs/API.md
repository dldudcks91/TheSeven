# API 명세서

## 공통 규칙

### 요청 형식

모든 게임 API는 `POST /api` 단일 엔드포인트로 처리.

```json
{
    "user_no": 1,
    "api_code": 2003,
    "data": {}
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| user_no | int | 사용자 번호 |
| api_code | int | API 식별 코드 |
| data | dict | API별 파라미터 |

### 응답 형식

```json
{
    "success": true,
    "message": "설명 문자열",
    "data": {}
}
```

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

---

## 시스템 API (1xxx)

### 1002 - 게임 데이터 전체 조회

서버 메모리에 로드된 모든 CSV 게임 설정 반환. 클라이언트 초기화 시 1회 호출.

- **data**: `{}` (파라미터 없음)
- **응답 data**: `{building, research, unit, buff, item, mission, mission_index, shop}` 구조의 전체 config

---

### 1003 - 신규 유저 생성

- **data**: `{}` (파라미터 없음)
- **응답 data**: 생성된 `user_no`

---

### 1010 - 로그인 (전체 데이터 로드)

로그인 시 해당 유저의 모든 게임 데이터를 Redis에 캐싱하고 반환. 진행 중인 유닛 훈련/연구 작업을 Task Queue에 재등록.

- **data**: `{}` (파라미터 없음)
- **응답 data**:
```json
{
    "buildings": {},
    "units": {},
    "researches": {},
    "resources": {},
    "buffs": {},
    "items": {},
    "missions": {},
    "shops": {}
}
```

---

### 1011 - 자원 정보 조회

- **data**: `{}`
- **응답 data**:
```json
{
    "user_no": 1,
    "food": 10000,
    "wood": 10000,
    "stone": 10000,
    "gold": 10000,
    "ruby": 100
}
```

---

### 1012 - 버프 정보 조회

- **data**: `{}`
- **응답 data**: `{permanent_buffs: {...}, temporary_buffs: [...], total_buffs: {...}}`

---

### 1013 - 버프 총합 조회

총합만 반환 (전투, 자원생산 계산용).

- **data**: `{}`
- **응답 data**: `{total_buffs: {"unit:attack:infantry": 15.0, ...}}`

---

### 1014 - 타입별 버프 총합 조회

특정 target_type의 버프 총합만 반환.

- **data**: `{"target_type": "unit"}`
- **응답 data**: `{target_type: "unit", total_buffs: {"unit:attack:infantry": 15.0, ...}}`

---

## 건물 API (2xxx)

건물 상태값: `0` = 완료(idle), `1` = 건설 중, `2` = 업그레이드 중

건물 인덱스 목록: `101, 201, 301, 401`
최대 레벨: `10`

### 2001 - 건물 정보 조회

- **data**: `{}`
- **응답 data**: `{building_idx: {building_idx, building_lv, status, start_time, end_time, target_level}}` 딕셔너리

---

### 2002 - 건물 생성 (최초 건설)

아직 존재하지 않는 건물을 처음 생성. DB에 직접 삽입 후 Redis에 캐싱.

- **data**: `{"building_idx": 101}`
- **처리 순서**:
  1. AVAILABLE_BUILDINGS 목록 확인
  2. 이미 존재 여부 확인 (Redis)
  3. GameDataManager에서 Lv1 비용/시간 조회
  4. `ResourceManager.consume_resources()` 원자적 자원 차감
  5. BuffManager에서 건설 속도 버프 적용 (최대 90% 단축)
  6. DB 삽입 → Redis 캐싱
- **응답 data**: 생성된 건물 데이터

---

### 2003 - 건물 업그레이드

- **data**: `{"building_idx": 101}`
- **처리 순서**:
  1. Redis에서 건물 조회 → status == 0 확인
  2. target_level config 조회
  3. `ResourceManager.consume_resources()` 원자적 자원 차감
  4. 버프 적용 → Redis 상태 업데이트 (status: 2)
- **응답 data**: 업데이트된 건물 데이터 + consumed_resources, remaining_resources

---

### 2004 - 건물 업그레이드 완료

end_time이 지난 건물을 완료 처리. MissionManager를 호출해 건물 관련 미션 업데이트.

- **data**: `{"building_idx": 101}`
- **응답 data**: `{building: {...}, mission_update: {...}}`

---

### 2005 - 건물 건설/업그레이드 취소

자원 환불 포함. 건설 중(status=1)이면 Redis에서 삭제, 업그레이드 중(status=2)이면 status=0으로 복구.

- **data**: `{"building_idx": 101, "refund_percent": 100}`
- **응답 data**: `{building_idx, action, refund_resources, refund_percent}`

---

### 2006 - 완료된 건물 일괄 처리

end_time이 지난 status=2 건물을 모두 자동 완료.

- **data**: `{}`
- **응답 data**: `{buildings: [{building_idx, new_level}, ...]}`

---

### 2007 - 건물 가속

업그레이드 중(status=2)인 건물의 완료 시간을 단축. 단축 후 end_time이 현재 시간 이전이면 즉시 완료 가능 상태.

- **data**: `{"building_idx": 101, "speedup_seconds": 300}`
- **응답 data**: 업데이트된 건물 데이터 (end_time 변경 반영)

---

## 연구 API (3xxx)

### 3001 - 연구 정보 조회

- **data**: `{}`
- **응답 data**: `{research_idx: {research_idx, research_lv, status, start_time, end_time}}` 딕셔너리

---

### 3002 - 연구 시작

- **data**: `{"research_idx": 1001, "research_lv": 1}`
- **처리**: 비용 차감 → Redis 큐에 완료 시각 등록 → Redis 상태 업데이트

---

### 3003 - 연구 완료

- **data**: `{"research_idx": 1001}`
- **처리**: end_time 검증 → Redis 상태 완료로 변경 → 연구 완료 버프 활성화

---

### 3004 - 연구 취소

- **data**: `{"research_idx": 1001}`
- **처리**: Redis 큐에서 제거 → 상태 복구 → 자원 환불

---

## 유닛 API (4xxx)

유닛 인덱스 범위: `401 ~ 424`

### 4001 - 유닛 정보 조회

- **data**: `{}`
- **응답 data**: `{unit_idx: {unit_idx, count, status, ...}}` 딕셔너리

---

### 4002 - 유닛 훈련

- **data**: `{"unit_idx": 401, "quantity": 10}`
- **처리**: 비용 차감 → Redis Task Queue에 완료 시각 등록
- TaskWorker가 완료 시각 도달 시 자동으로 `unit_finish()` 처리 + WebSocket 알림

---

### 4003 - 유닛 업그레이드

- **data**: `{"unit_idx": 401, "target_unit_idx": 402, "quantity": 1}`
- **처리**: 비용 차감 → Redis Task Queue에 완료 시각 등록 → 원본 유닛 upgrading 수량 차감

---

### 4004 - 유닛 완료 (unit_finish)

- **data**: `{"unit_idx": 401, "unit_type": 0}`
- **처리**: 완료 시간 확인 → 훈련: training→ready 이동 / 업그레이드: upgrading→target ready 이동 → Redis 큐 삭제
- TaskWorker가 자동 호출하지만, 클라이언트에서 수동 호출도 가능

---

### 4005 - 유닛 취소 (unit_cancel)

- **data**: `{"unit_idx": 401}`
- **처리**: Redis metadata에서 task 조회 → 자원 100% 환불 → 캐시 상태 복원 → Redis 큐 삭제

---

### 4006 - 유닛 즉시 완료 (unit_speedup)

- **data**: `{"unit_idx": 401}`
- **처리**: Redis completion_time을 현재 시각으로 변경 → TaskWorker가 다음 사이클에 완료 처리

---

## 미션 API (5xxx)

미션 카테고리: `building, unit, research, hero, battle, resource`

### 5001 - 미션 정보 조회

- **data**: `{}`
- **응답 data**: `{mission_idx: {mission_idx, is_completed, is_claimed, ...}}` 딕셔너리

---

### 5002 - 미션 보상 수령

- **data**: `{"mission_idx": 101001}`
- **처리**: is_completed == true 확인 → is_claimed 아님 확인 → 보상(아이템/자원) 지급 → is_claimed = true

---

## 아이템 API (60xx)

### 6001 - 아이템 정보 조회

- **data**: `{}`
- **응답 data**: `{item_idx: {item_idx, quantity}}` 딕셔너리

---

### 6002 - 아이템 획득 (개발/테스트용)

- **data**: `{"item_idx": 1001, "quantity": 1}`

---

### 6003 - 아이템 사용

- **data**: `{"item_idx": 1001}`
- **처리**: item_info.csv에서 category/effect 조회 → 효과 적용 (자원 추가, 버프 활성화 등)

---

## 상점 API (601x)

### 6011 - 상점 정보 조회

- **data**: `{}`
- **응답 data**: 현재 상점에 진열된 아이템 목록

---

### 6012 - 상점 새로고침

- **data**: `{}`
- **처리**: shop_info.csv의 weight 기반 랜덤 아이템 재생성

---

### 6013 - 상점 구매

- **data**: `{"slot": 0}`
- **처리**: 자원 차감 → 인벤토리에 아이템 추가

---

## 연맹 API (7xxx)

### 7001 - 연맹 정보 조회

- **data**: `{}`
- **응답 data**: 연맹 기본 정보 (이름, 레벨, 경험치, 공지 등)

---

### 7002 - 연맹 생성

- **data**: `{"name": "연맹명"}`
- **처리**: 이름 중복 확인 → Redis에 연맹 데이터 생성 → 생성자를 리더로 등록

---

### 7003 - 연맹 가입 신청

- **data**: `{"alliance_no": 1}`
- **처리**: join_type에 따라 즉시 가입 or 신청 대기

---

### 7004 - 연맹 탈퇴

- **data**: `{}`

---

### 7005 - 연맹 검색

- **data**: `{"keyword": "연맹명"}`
- **응답 data**: 검색 결과 연맹 목록

---

### 7006 - 연맹 멤버 목록 조회

- **data**: `{}`
- **응답 data**: `{user_no: {nickname, role, contribution, ...}}` 딕셔너리

---

### 7007 - 멤버 추방 (리더/임원 전용)

- **data**: `{"target_user_no": 2}`

---

### 7008 - 멤버 직위 변경

- **data**: `{"target_user_no": 2, "new_position": 3}`
- **직위 코드**: `1` = 맹주, `2` = 부맹주, `3` = 임원, `4` = 일반
- **참고**: 맹주(1) 위임 시 요청자가 일반(4)으로 강등됨

---

### 7009 - 가입 신청 목록 조회 (리더/임원 전용)

- **data**: `{}`
- **응답 data**: 신청자 목록

---

### 7010 - 가입 신청 승인/거절

- **data**: `{"target_user_no": 2, "approve": true}`

---

### 7011 - 연맹 경험치 기부

- **data**: `{"resource_type": "gold", "amount": 100}`
- **처리**: 자원 차감 → 연맹 경험치/코인 적립 (alliance_donate config 기반 비율 적용)

---

### 7012 - 연맹 가입 방식 변경 (리더 전용)

- **data**: `{"join_type": "free"}` (`"free"`: 자유 가입, `"approval"`: 신청 필요)

---

### 7013 - 연맹 해산 (리더 전용)

- **data**: `{}`
- **처리**: Redis에서 연맹 데이터 삭제 → AllianceSyncWorker가 DB에서도 삭제

---

### 7014 - 연맹 공지 조회

- **data**: `{}`
- **응답 data**: 연맹 공지 문자열

---

### 7015 - 연맹 공지 작성 (리더/임원 전용)

- **data**: `{"notice": "공지 내용"}`

---

### 7016 - 연맹 연구 목록 조회

- **data**: `{}`
- **응답 data**: `{research_idx: {research_idx, research_lv, ...}}` 딕셔너리

---

### 7017 - 연맹 연구 진행

- **data**: `{"research_idx": 8001}`

---

## 영웅 API (8xxx)

### 8001 - 영웅 목록 조회

전체 영웅 도감 + 보유 여부 반환.

- **data**: `{}`
- **응답 data**:
```json
{
    "heroes": [
        {
            "hero_idx": 1,
            "korean_name": "아서",
            "hero_lv": 5,
            "exp": 1200,
            "owned": true
        }
    ]
}
```

---

### 8002 - 영웅 지급 (테스트/포트폴리오용)

특정 영웅을 유저에게 지급.

- **data**: `{"hero_idx": 1}`
- **응답 data**: 지급 결과

---

## 전투 API (9xxx)

행군 상태값: `marching` (이동 중), `battling` (전투 중), `returning` (귀환 중), `completed` (완료)

행군 대상: `target_type = "user"` (유저 공격) | `"npc"` (NPC 사냥)

### 9001 - 내 맵 좌표 조회

맵에서 나의 현재 위치 반환.

- **data**: `{}`
- **응답 data**: `{"x": 42, "y": 17}`

---

### 9002 - 맵 정보 조회

주변 유저, NPC 위치, 내 행군 목록 포함.

- **data**: `{}`
- **응답 data**:
```json
{
    "my_position": {"x": 42, "y": 17},
    "map_size": 100,
    "nearby_users": [{"user_no": 2, "x": 50, "y": 30}],
    "npcs": [{"npc_id": "uuid", "npc_idx": 101, "x": 20, "y": 80, "alive": true, "tier": 1, "korean_name": "고블린"}],
    "marches": [...]
}
```

---

### 9003 - NPC 목록 조회

현재 맵의 모든 NPC 상태 반환.

- **data**: `{}`
- **응답 data**:
```json
{
    "npcs": [
        {
            "npc_id": "uuid",
            "npc_idx": 101,
            "x": 20, "y": 80,
            "alive": true,
            "tier": 1,
            "korean_name": "고블린 부족",
            "exp_reward": 50
        }
    ]
}
```

---

### 9011 - 행군 목록 조회

현재 진행 중인 내 행군 목록.

- **data**: `{}`
- **응답 data**:
```json
{
    "marches": [
        {
            "march_id": "uuid",
            "status": "marching",
            "target_type": "npc",
            "from_x": 42, "from_y": 17,
            "to_x": 20, "to_y": 80,
            "departure_time": "2026-03-01T12:00:00",
            "arrival_time": "2026-03-01T12:05:00",
            "return_time": null,
            "units": {"401": 100},
            "hero_idx": 1
        }
    ]
}
```

---

### 9012 - 행군 생성 (출진)

유저 공격 또는 NPC 사냥 출진.

- **data**:
```json
{
    "target_type": "npc",
    "npc_id": "uuid",
    "units": {"401": 100},
    "hero_idx": 1
}
```
또는 유저 공격:
```json
{
    "target_type": "user",
    "target_user_no": 2,
    "units": {"401": 100},
    "hero_idx": 1
}
```
- **제약**:
  - 동시 행군 최대 3개
  - 유닛 ready 수량 초과 불가
  - hero_idx는 선택값
- **응답 data**: `{"march_id": "uuid", "arrival_time": "..."}`

---

### 9013 - 행군 취소

이동 중인 행군만 취소 가능 (battling 상태 취소 불가).

- **data**: `{"march_id": "uuid"}`
- **처리**: 행군 삭제 → 유닛 반환
- **응답 data**: `{}`

---

### 9021 - 전투 정보 조회

진행 중인 전투 상세 정보.

- **data**: `{"battle_id": "uuid"}`
- **응답 data**: 전투 상태, 라운드, 병력 현황

---

### 9022 - 전투 보고서 조회

완료된 전투 결과 조회.

- **data**: `{"battle_id": "uuid"}`
- **응답 data**:
```json
{
    "battle_id": "uuid",
    "attacker_win": true,
    "rounds": 12,
    "attacker_losses": {"401": 10},
    "defender_losses": {"401": 50},
    "loot": {"food": 200, "wood": 100},
    "hero_exp": 150
}
```

---

## 집결(Rally) API (903x)

### 9031 - 집결 생성

Leader가 NPC 집결을 시작한다. 연맹 가입 필수.

- **data**: `{"target_type": "npc", "npc_id": 1, "units": {"401": 50}, "hero_idx": 1, "recruit_window": 1}`
- **recruit_window**: 1 또는 5 (분)
- **응답 data**:
```json
{
    "rally_id": 1,
    "recruit_expire": "2026-03-09T12:01:00",
    "recruit_window": 1
}
```

### 9032 - 집결 참여

연맹 멤버가 집결에 병사를 보낸다. gather 행군 생성.

- **data**: `{"rally_id": 1, "units": {"401": 30}}`
- **응답 data**:
```json
{
    "rally_id": 1,
    "march_id": 10,
    "arrival_time": "2026-03-09T12:00:30"
}
```

### 9033 - 집결 정보 조회

집결 상태 및 참여 멤버 목록 조회.

- **data**: `{"rally_id": 1}`
- **응답 data**:
```json
{
    "rally": {"rally_id": 1, "status": "recruiting", "leader_no": 1, "...": "..."},
    "members": [{"user_no": 1, "units": {"401": 50}, "status": "arrived"}]
}
```

### 9034 - 집결 멤버 추방

Leader만 가능. 추방된 멤버는 본인 성으로 귀환.

- **data**: `{"rally_id": 1, "target_user_no": 2}`

### 9035 - 집결 취소

Leader만 가능. 전체 멤버 귀환 처리 후 집결 삭제.

- **data**: `{"rally_id": 1}`

---

## WebSocket 이벤트 (전투)

클라이언트가 `/ws/{user_no}`로 연결 후 수신하는 전투 관련 Push 이벤트.

### battle_start

전투 시작 시 공격자/수비자에게 전송.

```json
{
    "type": "battle_start",
    "data": {
        "battle_id": 1,
        "battle_type": "user",
        "x": 50, "y": 50,
        "atk_user_no": 1,
        "atk_hero_lv": 5,
        "atk_max_hp": 10000,
        "atk_units": {"401": 100},
        "def_user_no": 2,
        "def_max_hp": 5000,
        "def_units": {"401": 50}
    }
}
```

### battle_tick

매 라운드 결과 (공격자/수비자/구독자에게 전송).

```json
{
    "type": "battle_tick",
    "data": {
        "battle_id": 1,
        "round": 3,
        "atk_units": {"401": 95},
        "def_units": {"401": 30}
    }
}
```

### battle_end

전투 종료 시 공격자/수비자/구독자에게 전송.

```json
{
    "type": "battle_end",
    "data": {
        "battle_id": 1,
        "result": "attacker_win"
    }
}
```

| result 값 | 의미 |
|-----------|------|
| attacker_win | 공격자 승리 |
| defender_win | 수비자 승리 |
| draw | 상호 전멸 |

### battle_incoming

수비자에게만 전송. 새 공격이 도착했음을 알림.

```json
{
    "type": "battle_incoming",
    "data": {"battle_id": 1}
}
```

### battle_bloodless

무혈입성 (수비 병력 0일 때). 공격자에게 전송.

```json
{
    "type": "battle_bloodless",
    "data": {
        "bloodless": true,
        "battle_id": 1,
        "battle_type": "user",
        "x": 50, "y": 50,
        "atk_user_no": 1,
        "atk_hero_lv": 0,
        "def_user_no": 2,
        "loot": {"food": 2000, "wood": 1000, "stone": 500, "gold": 300},
        "return_time": "2026-03-09T12:10:00"
    }
}
```

### battle_bloodless_defend

무혈입성 시 수비자에게 전송. data 구조는 `battle_bloodless`와 동일.

### map_march_update

맵 전체 브로드캐스트. 행군 상태 변경 시.

```json
{
    "type": "map_march_update",
    "data": {
        "march_id": 1,
        "status": "battling",
        "return_time": null
    }
}
```

| status 값 | 의미 |
|-----------|------|
| battling | 전투 중 |
| returning | 귀환 중 |

### map_march_complete

맵 전체 브로드캐스트. 행군 완전 완료 (귀환 도착).

```json
{
    "type": "map_march_complete",
    "data": {"march_id": 1}
}
```

### battlefield_tick

전장 구독자에게 1초마다 전송. 전장 내 전투 요약.

```json
{
    "type": "battlefield_tick",
    "bf_id": 1,
    "battles": [
        [1, 50, 50, 85, 60, 3]
    ]
}
```

battles 배열 형식: `[battle_id, x, y, atk_hp_%, def_hp_%, round]`

---

## 비게임 REST API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 헬스체크 (Redis, GameData, WebSocket, Worker 상태) |
| GET | `/pool-status` | Redis/DB 커넥션 풀 상세 통계 |
| WS | `/ws/{user_no}` | WebSocket 연결 (게임 이벤트 수신) |
