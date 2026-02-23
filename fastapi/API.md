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
- **응답 data**: `{buff_idx: {...버프 데이터}}` 딕셔너리

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

## 연구 API (3xxx)

### 3001 - 연구 정보 조회

- **data**: `{}`
- **응답 data**: `{research_idx: {research_idx, research_lv, status, start_time, end_time}}` 딕셔너리

---

### 3002 - 연구 시작

- **data**: `{"research_idx": 1001}`
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

- **data**: `{"unit_idx": 401, "count": 10}`
- **처리**: 비용 차감 → Redis Task Queue에 완료 시각 등록
- TaskWorker가 완료 시각 도달 시 자동으로 `unit_finish()` 처리 + WebSocket 알림

---

### 4003 - 유닛 업그레이드

- **data**: `{"unit_idx": 401}`

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

- **data**: `{"item_idx": 1001}`
- **처리**: 자원 차감 → 인벤토리에 아이템 추가

---

## 연맹 API (7xxx)

### 7001 - 연맹 정보 조회

- **data**: `{}`
- **응답 data**: 연맹 기본 정보 (이름, 레벨, 경험치, 공지 등)

---

### 7002 - 연맹 생성

- **data**: `{"alliance_name": "연맹명"}`
- **처리**: 이름 중복 확인 → Redis에 연맹 데이터 생성 → 생성자를 리더로 등록

---

### 7003 - 연맹 가입 신청

- **data**: `{"alliance_id": 1}`
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

- **data**: `{"target_user_no": 2, "new_role": "officer"}`

---

### 7009 - 가입 신청 목록 조회 (리더/임원 전용)

- **data**: `{}`
- **응답 data**: 신청자 목록

---

### 7010 - 가입 신청 승인/거절

- **data**: `{"target_user_no": 2, "approve": true}`

---

### 7011 - 연맹 경험치 기부

- **data**: `{"amount": 100}`

---

### 7012 - 연맹 가입 방식 변경 (리더 전용)

- **data**: `{"join_type": 0}` (0: 자유 가입, 1: 신청 필요)

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

## 비게임 REST API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 헬스체크 (Redis, GameData, WebSocket, Worker 상태) |
| GET | `/pool-status` | Redis/DB 커넥션 풀 상세 통계 |
| WS | `/ws/{user_no}` | WebSocket 연결 (게임 이벤트 수신) |
