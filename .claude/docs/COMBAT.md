# COMBAT.md - 전투 시스템 설계 문서

> **프로젝트**: TheSeven
> **최종 수정**: 2026-03-03

---

## 1. 개요

### 1.1 핵심 원칙

- **Arrive-then-fight**: 이동 중 전투 없음. 목적지 도착 후 전투 시작
- **Redis-first**: 전투 상태는 Redis에서 관리. DB는 결과 기록용
- **1초 틱**: BattleWorker가 1초마다 `battle:active`를 순회하여 라운드 계산
- **WebSocket**: 전투 이벤트 실시간 Push (BattleWorker → 참여자/전체)

### 1.2 공격 유형 5가지

| # | 유형 | 대상 | 집결 | 약탈 | 상태 |
|---|------|------|------|------|------|
| 1 | **NPC 공격** | NPC | ❌ | ❌ (EXP) | ✅ 구현 완료 |
| 2 | **NPC 집결** | NPC | ✅ | ❌ (EXP) | ⬜ 예정 |
| 3 | **성 일반공격** | 플레이어 성 | ❌ | ✅ | 📋 기획 확정 |
| 4 | **성 집결공격** | 플레이어 성 | ✅ | ✅ | 📋 기획 확정 |
| 5 | **거점 집결공격** | 전략 거점 | ✅ | ❌ | ⬜ 예정 |

> 📋 기획 확정 = 설계 완료, 구현 예정
> ⬜ 예정 = 기본 방향만 결정, 상세 설계 미완

### 1.3 구현 현황

```
✅ Phase 1: 맵 & 위치
✅ Phase 2: 행군 (March)
✅ Phase 3: 전투 계산 — Python 1차 (1v1 기준)
✅ Phase 4: NPC 공격
✅ Phase 5: 클라이언트 & 실시간 맵 동기화
📋 Phase 6: 성 일반공격 / 성 집결공격 (구현 예정)
⬜ Phase 7: C++ calculate_round() 포팅
⬜ Phase 8: NPC 집결 / 거점 집결 (미설계)
```

---

## 2. 공통 시스템

### 2.1 맵 & 좌표

- **맵 크기**: 100 × 100 (좌표 0 ~ 99)
- **성 배치**: 계정 생성 시 서버가 랜덤 좌표 배정 (중복 제외)
- **이동 거리**: 유클리드 거리 `√(dx² + dy²)`
- **이동 시간**: `거리 / march_speed` (초 단위)
- **행군 속도**: `unit.speed × 10 타일/분` — 보병 20, 기병 30, 궁병 10 (혼합 편성 시 최솟값 적용)
- **동시 행군**: 플레이어당 최대 3개

```
map:positions → Hash
  key:   user_no (str)
  value: "x,y"
```

서버 시작 시 DB 전체 로드. 성 생성 시 즉시 업데이트.

> **확장 방향 (포트폴리오 언급용)**: 현재 O(N) 전체 스캔 → `Redis GEOADD / GEORADIUS` O(N + log M)

### 2.2 행군 공통 흐름

```
march_create()
  → 보유 행군 수 체크 (최대 3)
  → 출진 가능 유닛 확인 (ready 상태)
  → 영웅 중복 출전 체크
  → 이동 시간 계산
  → 유닛 상태: ready → field
  → DB: March 레코드 생성 (march_type 포함)
  → Redis: completion_queue:march 등록 (score = 도착 timestamp)
  → WebSocket: map_march_start 브로드캐스트

TaskWorker (만료된 march 감지)
  → march_type에 따라 분기
  → 도착 처리 (battle_start 또는 rally 도착 처리)
  → WebSocket: map_march_update 브로드캐스트
```

#### March 테이블

```python
class March(Base):
    __tablename__ = 'march'
    march_id        : str       # UUID, PK
    user_no         : int       # 출발자
    target_user_no  : int       # nullable (NPC 공격 시 없음)
    npc_id          : str       # nullable (NPC 공격 시)
    rally_id        : str       # nullable (집결 소속 march)
    march_type      : str       # normal | rally_gather | rally_attack
    target_type     : str       # user | npc | stronghold
    from_x, from_y  : int
    to_x, to_y      : int
    units           : str       # JSON {"401": 100, "411": 50}
    hero_idx        : int       # nullable
    march_speed     : float
    departure_time  : datetime
    arrival_time    : datetime
    return_time     : datetime  # nullable
    status          : str       # marching | battling | returning | completed | cancelled
    battle_id       : str       # nullable
```

#### March Redis

```
completion_queue:march        → ZSet  (score=도착시각)
completion_queue:march_return → ZSet  (score=귀환시각)
march:{march_id}              → Hash  (행군 상세, 전투 중 조회용)
user_data:{user_no}:marches   → Set   (활성 march_id 목록)
```

### 2.3 집결 공통 흐름

집결공격(NPC 집결 / 성 집결 / 거점 집결) 공통 처리.

```
[1] 집결 생성 (Leader)
  rally_id 발급, recruit_window 설정, status = recruiting

[2] 모집 단계 (recruit_window 동안)
  멤버 참여 → Leader 성으로 행군 시작 (march_type: rally_gather)
  recruit_window 만료 → 신규 참여 불가 (status = waiting)

[3] 대기 단계
  Leader 관리 화면: 멤버별 도착까지 남은 시간 표시
  Leader 권한: 특정 멤버 제외 → 해당 march 즉시 귀환

[4] 출발 조건
  비제외 멤버 전원 Leader 성 도착 + 지정 시각 도달
  → 합산 병력 일괄 출발 (march_type: rally_attack)
  ※ 무한 대기 방지 없음 — Leader가 직접 제외 처리해야 함

[5] 전투
  합산 병력으로 단일 전투 처리
```

#### Rally 테이블

```python
class Rally(Base):
    __tablename__ = 'rally'
    rally_id        : str       # UUID, PK
    leader_user_no  : int
    target_user_no  : int       # nullable (NPC/거점 공격 시)
    target_npc_id   : str       # nullable
    target_type     : str       # user | npc | stronghold
    recruit_window  : int       # 초 단위 (60 or 300)
    status          : str       # recruiting | waiting | marching | done
    created_at      : datetime

class RallyMember(Base):
    __tablename__ = 'rally_member'
    rally_id        : str       # PK, FK → Rally
    user_no         : int       # PK
    units           : str       # JSON
    hero_idx        : int       # nullable
    gather_march_id : str       # rally_gather march ID
    status          : str       # gathering | arrived | excluded | routed
```

#### Rally Redis

```
rally:{rally_id}                      → Hash  (집결 상태)
rally:{rally_id}:members              → Hash  { user_no → JSON }
completion_queue:rally_gather         → ZSet  (score=도착시각, member="{rally_id}:{user_no}")
```

### 2.4 전투 계산 (calculate_round) ← C++ 교체 대상

```python
def calculate_round(attacker_units, defender_units,
                    attacker_hero=None, defender_hero=None,
                    round_no=0):
    """
    Returns:
        atk_damage : 공격자 → 수비자 데미지
        def_damage : 수비자 → 공격자 데미지
        skill_log  : 발동 스킬 설명
    """
    # 1. 기본 공격력 합산 (unit_info.csv 참조)
    atk_power = Σ { unit_attack × unit_count }
    def_power = Σ { unit_attack × unit_count }

    # 2. 영웅 보정
    if attacker_hero:
        atk_power *= (1 + attacker_hero.lv * 0.05)

    # 3. 병종 상성 적용 (예정)
    #    보병 vs 기병 : 1.5×
    #    기병 vs 궁병 : 1.5×
    #    궁병 vs 보병 : 1.5×

    # 4. 방어력 감소 (공식 미확정)

    # 5. 스킬 판정 (Hero 스킬 설계 후 추가)

    return atk_damage, def_damage, skill_log
```

**HP 계산:**
```
최대 HP = Σ { unit_health(CSV) × unit_count }
```

### 2.5 패주 & 귀환

```
전투 중 병력 HP → 0
  → march.status = "routed"
  → 즉시 귀환 큐 등록 (completion_queue:march_return)
  → WebSocket: map_march_update {status: returning} 브로드캐스트

전투 종료 (승패 확정)
  → 생존 공격자: march.status = "returning"
  → return_time = now + 이동 시간
  → completion_queue:march_return 등록
  → TaskWorker 감지 → 유닛 field → ready 복구
```

### 2.6 BattleWorker

```python
class BattleWorker:
    TICK_INTERVAL = 1.0  # 초

    async def run(self):
        while True:
            await self.process_all_battles()
            await asyncio.sleep(TICK_INTERVAL)

    async def process_all_battles(self):
        battle_ids = await redis.smembers('battle:active')
        for battle_id in battle_ids:
            await self.process_single_battle(battle_id)

    async def process_single_battle(self, battle_id):
        # 1. Redis 전투 상태 조회
        # 2. calculate_round() 호출
        # 3. HP 업데이트
        # 4. 종료 조건 체크
        # 5. WebSocket push
        # 6. 종료 시 battle_end() 처리
```

---

## 3. NPC 공격 ✅ 구현 완료

### 3.1 개요

단일 플레이어가 맵에 배치된 NPC를 공격. 승리 시 EXP 획득, NPC 리스폰.
약탈 없음. 영웅 EXP 수급 및 초반 콘텐츠 역할.

### 3.2 NPC 정보 (npc_info.csv)

```json
{
  "npc_id"       : "uuid",
  "npc_idx"      : 101,
  "korean_name"  : "고블린 부족",
  "tier"         : 1,
  "x"            : 20,
  "y"            : 80,
  "alive"        : true,
  "exp_reward"   : 50,
  "units"        : { "401": 30 },
  "respawn_min"  : 30
}
```

```
map:npcs → Hash  { npc_id → JSON }
completion_queue:npc_respawn → ZSet  (score=리스폰시각)
```

### 3.3 공격 흐름

```
march_create(target_type="npc", npc_id=...)
  → NPC alive 확인
  → March 생성 (march_type: normal, target_type: npc)
  → completion_queue:march 등록

TaskWorker (도착 감지)
  → NPC 병력 읽기
  → battle_start() → BattleWorker 등록

전투 종료 (공격자 승리)
  → NPC alive = false
  → 동행 영웅 EXP 지급 (add_hero_exp() → 레벨업 체크)
  → completion_queue:npc_respawn 등록

TaskWorker (리스폰 감지)
  → NPC alive = true, 위치 재배치
```

---

## 4. NPC 집결 ⬜ 예정 (미설계)

### 4.1 기본 방향

- 강한 고티어 NPC를 연맹원이 집결해서 공격
- 집결 흐름은 **섹션 2.3 공통 집결 흐름** 동일
- `target_type: npc` 로 Rally 생성
- 전투 결과: EXP 분배 방식 미결정

> 상세 설계 추후 진행.

---

## 5. 성 일반공격 📋 기획 확정

### 5.1 개요

공격자 여러 명이 동일한 성을 **개별 독립 전투**로 공격.
집결 없이 즉시 출발. 소규모 기습, 정찰, 다방면 압박에 활용.

### 5.2 스냅샷 방식 — 멀티 공격자 처리

동일 성을 공격 중인 Battle들을 1초 틱에 함께 처리.

```
[틱 시작]
  해당 성(defender_user_no)을 대상으로 하는 활성 battle_id 목록 조회
  수비 스냅샷 = 현재 수비 병력 (1회 읽기)

[개별 전투 계산] — 동일 스냅샷 기준, 순서 무관
  Battle_A: 수비(스냅샷) vs A  →  수비 손실 Y1, A 손실 X1
  Battle_B: 수비(스냅샷) vs B  →  수비 손실 Y2, B 손실 X2
  Battle_C: 수비(스냅샷) vs C  →  수비 손실 Y3, C 손실 X3

[틱 종료 — 일괄 업데이트]
  수비 병력 = 스냅샷 - (Y1 + Y2 + Y3)  ← Redis 1회 쓰기
  A 병력    = A - X1
  B 병력    = B - X2
  C 병력    = C - X3
```

#### Redis — 성 공격 그룹 추적

```
castle_battle:{defender_user_no} → Set  { battle_id, battle_id, ... }
```

BattleWorker가 이 Set을 기준으로 같은 성을 공격 중인 Battle들을 묶어서 처리.

### 5.3 밸런스 — 의도된 공격자 불리

```
수비 반격 DPS = 기본 DPS × 공격자 수
```

각 공격자가 수비 전체 병력과 독립 교전하므로, 공격자 수가 늘수록 개인 병력 소모가 빠름.

| 상황 | 수비 총 피해 | 공격 측 총 피해 |
|------|------------|---------------|
| 1명 공격 | DPS × 1 | DPS × 1 |
| 3명 공격 | DPS × 3 | DPS × 3 (각 1배) |

**의도**: 소수 개별 공격 → 불리 → **집결공격 자연 유도**.

**일반공격의 전략적 활용:**
- 약한 성 빠른 소탕
- 정찰 (수비 병력 규모 파악)
- 집결 준비 중 견제
- 다방면 동시 공격으로 수비 분산

### 5.4 전투 종료 조건

| 조건 | 결과 |
|------|------|
| 수비 병력 0 | 공격자 전원 승리 → 약탈 → 귀환 |
| 공격자 병력 0 | 해당 공격자 패주 → 나머지 전투 계속 |
| 모든 공격자 패주 | 수비 승리 |
| max_rounds 초과 | 무승부 → 공격자 자동 퇴각 |

> max_rounds 수치는 멀티 공격자 환경 고려하여 재검토 필요 (현재 50).

---

## 6. 성 집결공격 📋 기획 확정

### 6.1 개요

연맹원들이 **Leader 성에 집결** 후 목표 성으로 일괄 출발.
합산 병력으로 1회 전투 → 수비 반격이 분산되지 않아 일반공격 대비 효율적.

```
일반공격 (3명): 수비 반격 DPS × 3  (각 공격자에게 전체 DPS)
집결공격 (3명): 수비 반격 DPS × 1  (합산 병력이 1회 맞음)
```

### 6.2 집결 흐름

섹션 2.3 공통 집결 흐름 기반. `target_type: user` 로 Rally 생성.

```
recruit_window: 1분 / 5분 선택
집결장: Leader 성
출발 조건: 비제외 멤버 전원 도착 + 지정 시각 도달
전투: 합산 병력 vs 수비 (1회 전투, 기존 BattleWorker 활용)
```

### 6.3 Leader 관리 화면

```
집결 현황
  목표 성    : [플레이어명]
  모집 마감  : 3분 24초 / 만료
  -------------------------------------------
  멤버명  | 병력          | 도착까지  | 제외
  User_A  | 보병 500      | 도착 완료 | [제외]
  User_B  | 기병 300      | 1분 20초  | [제외]
  User_C  | 궁병 200      | 이동 중   | [제외]
  -------------------------------------------
  합산    | 보병 500 / 기병 300 / 궁병 200
```

---

## 7. 거점 집결공격 ⬜ 예정 (미설계)

### 7.1 기본 방향

- **집결공격 전용** (일반공격 불가)
- 거점 점령 시 연맹 단위 버프 예정
- **연맹별 거점** 시스템 추후 추가
- `target_type: stronghold` 로 Rally 생성

> 상세 설계 추후 진행.

---

## 8. 약탈

### 8.1 발생 조건

| 유형 | 약탈 |
|------|------|
| NPC 공격 / NPC 집결 | ❌ (EXP만) |
| 성 일반공격 승리 | ✅ |
| 성 집결공격 승리 | ✅ |
| 거점 집결 | ❌ |

### 8.2 계산

```
약탈량 = 수비자 각 자원 × 약탈 비율 (20%)
```

- 약탈 자원: 공격자 Redis 자원 즉시 추가
- 수비자 자원: Redis 즉시 차감
- 수송 용량 상한 / 다중 공격자 약탈 분배 방식: 미결정

### 8.3 무혈입성

```
수비 주둔 병력 0명 → 전투 없이 즉시 약탈 처리
```

---

## 9. 영웅 시스템

### 9.1 Hero 테이블

```python
class Hero(Base):
    __tablename__ = 'hero'
    user_no   : int  # PK
    hero_idx  : int  # PK
    hero_lv   : int  # DEFAULT 1
    exp       : int  # DEFAULT 0
```

### 9.2 전투 연동

- 행군 시 영웅 1명 선택 동행 (optional)
- 전투 보정: `공격력 × (1 + hero_lv × 0.05)`
- **중복 출전 방지**: march_create 시 활성 행군 hero_idx 충돌 체크

### 9.3 EXP 획득 (NPC 처치)

```
NPC 처치 → 동행 영웅 exp += npc_info.exp_reward
누적 EXP ≥ 레벨 임계값 → hero_lv += 1
```

### 9.4 스킬 시스템 (미설계)

```
hero_skill.csv 구조 예정:
  hero_idx, skill_idx, trigger_type (round/hp_percent),
  trigger_value, effect_type (damage/buff), value
```

---

## 10. DB 스키마

### 10.1 StatNation (컬럼 추가)

```python
map_x : Mapped[Optional[int]]
map_y : Mapped[Optional[int]]
```

### 10.2 March

섹션 2.2 참조. `march_type`, `rally_id` 포함.

### 10.3 Battle

```python
class Battle(Base):
    __tablename__ = 'battle'
    battle_id        : str       # UUID, PK
    march_id         : str       # FK → March (집결공격은 rally_attack march)
    attacker_user_no : int
    defender_user_no : int       # nullable (NPC 공격 시)
    npc_id           : str       # nullable
    start_time       : datetime
    end_time         : datetime  # nullable
    status           : str       # ongoing | attacker_win | defender_win | draw
    total_rounds     : int       # nullable
    attacker_loss    : str       # JSON
    defender_loss    : str       # JSON
    loot             : str       # JSON
```

> **상세 로그**: Redis `battle:{battle_id}:log` (List, TTL 24h). DB에는 요약만 저장.

### 10.4 Rally / RallyMember

섹션 2.3 참조.

### 10.5 Hero

섹션 9.1 참조.

---

## 11. Redis 키 구조

| 키 | 타입 | 내용 |
|----|------|------|
| `map:positions` | Hash | `{user_no → "x,y"}` |
| `map:npcs` | Hash | `{npc_id → JSON}` |
| `march:{march_id}` | Hash | 행군 상세 |
| `user_data:{user_no}:marches` | Set | 활성 march_id 목록 |
| `completion_queue:march` | ZSet | score = 도착시각 |
| `completion_queue:march_return` | ZSet | score = 귀환시각 |
| `completion_queue:npc_respawn` | ZSet | score = 리스폰시각 |
| `battle:{battle_id}` | Hash | 전투 실시간 상태 |
| `battle:{battle_id}:log` | List | 라운드별 로그 (TTL 24h) |
| `battle:active` | Set | 진행 중 battle_id |
| `battle_subscribers:{battle_id}` | Set | 관전 중인 user_no 목록 |
| `castle_battle:{user_no}` | Set | 해당 성 공격 중인 battle_id (성 일반공격용) |
| `rally:{rally_id}` | Hash | 집결 상태 |
| `rally:{rally_id}:members` | Hash | `{user_no → JSON}` |
| `completion_queue:rally_gather` | ZSet | score = 도착시각, member = `{rally_id}:{user_no}` |
| `battlefield:{bf_id}:members` | Hash | `{user_no → JSON(castle_x, castle_y, joined_at)}` |
| `battlefield:{bf_id}:subscribers` | Set | battlefield_tick 수신 user_no (멤버 자동 포함) |
| `battlefield:{bf_id}:battles` | Set | 전장 내 진행 중인 battle_id |
| `user_data:{user_no}:battlefield` | String | 참여 중인 bf_id (없으면 키 없음) |

---

## 12. API 코드

| 코드 | 메서드 | 설명 | 상태 |
|------|--------|------|------|
| 9001 | `my_position` | 내 성 좌표 조회 | ✅ |
| 9002 | `map_info` | 맵 전체 (플레이어/NPC/행군) | ✅ |
| 9003 | `npc_list` | NPC 목록 조회 | ✅ |
| 9011 | `march_list` | 내 행군 목록 | ✅ |
| 9012 | `march_create` | 출진 (normal / rally_gather / rally_attack) | ✅ |
| 9013 | `march_cancel` | 행군 취소 (marching 상태만) | ✅ |
| 9021 | `battle_info` | 진행 중 전투 상태 | ✅ |
| 9022 | `battle_report` | 전투 결과 리포트 | ✅ |
| 9031 | `rally_create` | 집결 생성 | 📋 |
| 9032 | `rally_join` | 집결 참여 | 📋 |
| 9033 | `rally_info` | 집결 현황 (Leader 관리 화면) | 📋 |
| 9034 | `rally_kick` | 멤버 제외 | 📋 |
| 9035 | `rally_cancel` | 집결 취소 | 📋 |
| 9040 | `battle_watch` | 전투 관전 시작 (스냅샷 + 구독 등록) | 📋 |
| 9041 | `battle_unwatch` | 관전 종료 (구독 해제) | 📋 |
| 9050 | `battlefield_list` | 전장 1~3 현황 (참여자 수, 구독자 수) | ✅ |
| 9051 | `battlefield_join` | 전장 참여 (성 투입) | ✅ |
| 9052 | `battlefield_retreat` | 전장 후퇴 | ✅ |
| 9053 | `battlefield_info` | 전장 스냅샷 (참여자 위치 + 진행 중 전투) | ✅ |
| 9054 | `battlefield_watch` | 전장 관전 시작 (구독 + 스냅샷) | ✅ |
| 9055 | `battlefield_unwatch` | 전장 관전 종료 | ✅ |

---

## 13. WebSocket 이벤트

### 13.1 전송 방식 — Binary vs JSON

고빈도 틱 데이터와 저빈도 이벤트를 분리.

| 이벤트 | 형식 | 트리거 | 수신자 |
|--------|------|--------|--------|
| `battle_tick` | **Binary struct** | 1초 틱 | 공격자, 수비자, **관전자** |
| `battle_incoming` | JSON | 적 행군 도착 감지 | 수비자 |
| `battle_start` | JSON | 전투 시작 | 공격자, 수비자, **관전자** |
| `battle_end` | JSON | 전투 종료 | 공격자, 수비자, **관전자** |
| `battle_watch_start` | JSON | 관전 시작 응답 (현재 전투 스냅샷) | 관전자 |
| `march_return` | JSON | 병력 귀환 | 공격자 |
| `map_march_start` | JSON | 행군 생성 | 전체 |
| `map_march_update` | JSON | 상태 변경 (battling/returning) | 전체 |
| `map_march_complete` | JSON | 행군 종료/귀환 완료 | 전체 |
| `battlefield_tick` | JSON | 전장 집계 틱 (1초) | 전장 구독자 |
| `battlefield_join` | JSON | 유저 전장 참여 | 전장 구독자 |
| `battlefield_retreat` | JSON | 유저 전장 후퇴 | 전장 구독자 |

`battle_tick`만 Binary: 유일하게 초당 1회 반복 전송되는 메시지. 나머지는 비정기·1회성이라 JSON 유지.

---

### 13.2 battle_tick — Binary Struct

#### 메시지 타입 코드 (첫 1바이트)

클라이언트가 수신 메시지 종류를 식별하는 용도.

| 코드 | 이벤트 |
|------|--------|
| `0x01` | battle_tick |

> 추후 이벤트 추가 시 이 테이블에 코드 등록.

#### Struct 레이아웃 (총 52 bytes, Big-endian)

```
┌──────────────────────────────────────────────────────┐
│ HEADER  3 bytes                                       │
│   [1]  msg_type      uint8   0x01                    │
│   [2]  round_no      uint16  현재 라운드              │
├──────────────────────────────────────────────────────┤
│ META  1 byte                                          │
│   [1]  status        uint8   0=ongoing               │
│                              1=atk_win               │
│                              2=def_win               │
│                              3=draw                  │
├──────────────────────────────────────────────────────┤
│ ATTACKER  24 bytes                                    │
│   [4]  atk_hp        uint32  현재 HP                 │
│   [4]  atk_max_hp    uint32  최대 HP                 │
│   [4]  atk_dmg       uint32  이번 라운드 가한 데미지  │
│   [2]  atk_inf       uint16  남은 보병 수             │
│   [2]  atk_cav       uint16  남은 기병 수             │
│   [2]  atk_arc       uint16  남은 궁병 수             │
│   [2]  atk_inf_loss  uint16  이번 라운드 보병 손실    │
│   [2]  atk_cav_loss  uint16  이번 라운드 기병 손실    │
│   [2]  atk_arc_loss  uint16  이번 라운드 궁병 손실    │
├──────────────────────────────────────────────────────┤
│ DEFENDER  24 bytes  (동일 구조)                       │
│   [4]  def_hp        uint32                          │
│   [4]  def_max_hp    uint32                          │
│   [4]  def_dmg       uint32                          │
│   [2]  def_inf       uint16                          │
│   [2]  def_cav       uint16                          │
│   [2]  def_arc       uint16                          │
│   [2]  def_inf_loss  uint16                          │
│   [2]  def_cav_loss  uint16                          │
│   [2]  def_arc_loss  uint16                          │
└──────────────────────────────────────────────────────┘
총 52 bytes  (vs JSON ~400 bytes, 약 87% 감소)
```

**유닛 종류 집계**: 보병(401~404) / 기병(411~414) / 궁병(421~424) 각 티어를 합산.
티어별 세부 내역은 `battle_end` 리포트에서 제공.

---

### 13.3 battle_tick 데이터 생성 흐름

```
BattleWorker.process_single_battle(battle_id)
    │
    ├─ [1] Redis에서 현재 전투 상태 읽기
    │       atk_units: {"401": 850, "411": 300, "421": 200}
    │       def_units: {"401": 500, "421": 100}
    │       round_no, max_rounds
    │
    ├─ [2] calculate_round()  ← C++ 교체 예정
    │       입력  : atk_units, def_units, atk_hero, def_hero, round_no
    │       출력  : atk_dmg, def_dmg
    │               atk_losses = {"401": 45, "411": 12}
    │               def_losses = {"401": 120}
    │
    ├─ [3] 유닛 수 업데이트
    │       atk_units["401"] -= 45  →  805
    │       def_units["401"] -= 120 →  380
    │
    ├─ [4] HP 재계산
    │       atk_hp = Σ(remaining_count × unit_health)
    │
    ├─ [5] Redis 일괄 업데이트
    │
    └─ [6] Binary pack & WebSocket send
            # 유닛 종류별 합산
            atk_inf = sum(401~404 remaining)
            atk_inf_loss = sum(401~404 losses)

            data = struct.pack(
                ">BH B IIIHHHHHH IIIHHHHHH",
                0x01, round_no, status,
                atk_hp, atk_max_hp, atk_dmg,
                atk_inf, atk_cav, atk_arc,
                atk_inf_loss, atk_cav_loss, atk_arc_loss,
                def_hp, def_max_hp, def_dmg,
                def_inf, def_cav, def_arc,
                def_inf_loss, def_cav_loss, def_arc_loss,
            )
            await ws_manager.send_bytes(user_no, data)
```

---

### 13.4 성 일반공격 — 멀티 공격자 tick 분배

```
스냅샷 기반 계산 완료 후:
  수비 총 손실 = Y1 + Y2 + Y3 (전 공격자 합산)
  수비 현재 HP = 공유값 (업데이트 완료)

공격자 A 수신:
  atk_*     = A 자신의 병력 데이터
  atk_dmg   = A가 이번 라운드 수비에 가한 데미지
  def_*     = 공유 수비 HP (전체 합산 후)
  def_dmg   = 수비가 A에게 가한 데미지

공격자 B 수신:
  atk_*     = B 자신의 병력 데이터
  def_*     = 동일한 공유 수비 HP
```

공격자마다 개별 pack & send. 수비자 HP는 공유이므로 재조회 없이 동일 값 재사용.

---

### 13.5 JS 클라이언트 수신

```javascript
ws.onmessage = async (event) => {
    // binary frame 여부 확인
    if (!(event.data instanceof Blob)) return;

    const buf = await event.data.arrayBuffer();
    const v   = new DataView(buf);

    const msgType = v.getUint8(0);
    if (msgType !== 0x01) return;

    let o = 1;
    const round  = v.getUint16(o); o += 2;
    const status = v.getUint8(o);  o += 1;

    const readSide = () => ({
        hp:       v.getUint32(o),    o += 4,
        max_hp:   v.getUint32(o),    o += 4,
        dmg:      v.getUint32(o),    o += 4,
        inf:      v.getUint16(o),    o += 2,
        cav:      v.getUint16(o),    o += 2,
        arc:      v.getUint16(o),    o += 2,
        inf_loss: v.getUint16(o),    o += 2,
        cav_loss: v.getUint16(o),    o += 2,
        arc_loss: v.getUint16(o),    o += 2,
    });

    const atk = readSide();
    const def = readSide();

    renderBattleUI(round, status, atk, def);
};
```

---

### 13.6 필드별 계산 규칙

#### HP 관련 필드

| 필드 | 계산 시점 | 공식 |
|------|-----------|------|
| `atk_max_hp` | **전투 시작 1회** | `Σ(초기 unit_count × unit_health)` — Redis 저장, 매 틱 재계산 안 함 |
| `def_max_hp` | **전투 시작 1회** | 동일 |
| `atk_hp` | 매 틱 (손실 반영 후) | `Σ(remaining_count × unit_health)` |
| `def_hp` | 매 틱 (손실 반영 후) | 동일 |

#### 데미지 필드

| 필드 | 공식 | 설명 |
|------|------|------|
| `atk_dmg` | `Σ(def_loss[unit_idx] × unit_health)` | 이번 라운드 수비측 실제 파괴 HP |
| `def_dmg` | `Σ(atk_loss[unit_idx] × unit_health)` | 이번 라운드 공격측 실제 파괴 HP |

> net_attack (공격력 - 방어력) 값이 아니라, **실제로 파괴된 HP 합산**. 방어력 경감 + 마지막 유닛 오버킬 제외.

#### 유닛 종류별 집계

```
atk_inf = remaining[401] + remaining[402] + remaining[403] + remaining[404]
atk_cav = remaining[411] + remaining[412] + remaining[413] + remaining[414]
atk_arc = remaining[421] + remaining[422] + remaining[423] + remaining[424]

atk_inf_loss = loss[401] + loss[402] + loss[403] + loss[404]  ← 이번 라운드만 (누적 아님)
```

#### status 코드와 전송 순서

```
status = 0 (ongoing)  →  battle_tick binary 단독 전송
status = 1/2/3 (종료) →  battle_tick binary (최종 상태) → battle_end JSON 순서로 전송
```

종료 라운드에도 tick이 먼저 전송된다.
클라이언트는 `status != 0` 수신 시 UI 최종 업데이트 후 `battle_end` JSON을 기다린다.

#### uint16 범위 주의

`inf`, `cav`, `arc` 및 손실 필드는 uint16 (최대 65,535).
단일 유닛 종류 합계가 65,535 초과 시 서버에서 `min(값, 65535)` 클리핑 적용.

---

### 13.7 battle_start 이벤트

전투 시작 시 1회 전송. 공격자·수비자 모두 수신.
클라이언트는 이 데이터로 전투 UI 초기값(영웅, 좌표, 최대 HP)을 설정.

#### 수신자

| 대상 | 수신 이벤트 |
|------|------------|
| 공격자 | `battle_start` |
| 수비자 | `battle_start` + `battle_incoming` (알림용 추가 전송) |
| 관전자 | `battle_watch_start` (별도 스냅샷, 하단 참고) |

#### 데이터 구조

```json
{
  "type": "battle_start",
  "data": {
    "battle_id":    123,
    "battle_type":  "user",      // "user" | "npc"
    "x":            45,          // 전투 발생 좌표
    "y":            23,

    "atk_user_no":  101,
    "atk_hero_idx": 1,           // 영웅 없으면 null
    "atk_hero_lv":  15,
    "atk_max_hp":   500000,
    "atk_units":    {"401": 850, "411": 300, "421": 200},

    "def_user_no":  202,         // NPC면 0
    "def_npc_id":   null,        // NPC면 npc_id, 유저면 null
    "def_max_hp":   300000,
    "def_units":    {"401": 500, "421": 100}
  }
}
```

#### NPC 전투 예시

```json
{
  "type": "battle_start",
  "data": {
    "battle_id":    456,
    "battle_type":  "npc",
    "x":            12, "y": 8,
    "atk_user_no":  101,
    "atk_hero_idx": 2,
    "atk_hero_lv":  10,
    "atk_max_hp":   300000,
    "atk_units":    {"401": 500},
    "def_user_no":  0,
    "def_npc_id":   5,
    "def_max_hp":   150000,
    "def_units":    {"401": 300, "421": 100}
  }
}
```

> `atk_max_hp` / `def_max_hp`: 전투 시작 시 계산된 총 HP. battle_tick의 `atk_max_hp` 필드와 동일 값이므로 클라이언트는 이 값을 캐싱해 HP 바 렌더링에 사용.

---

### 13.8 관전(Spectator) 시스템

#### 관전 흐름

```
[1] 클라이언트: battle_watch(battle_id) 요청 (API 9040)
      ↓
[2] 서버: battle:{battle_id} 존재 여부 확인
          SADD battle_subscribers:{battle_id} {user_no}  ← Redis 구독 등록
      ↓
[3] 서버 → 관전자: battle_watch_start JSON (현재 전투 스냅샷)
      {
        "battle_id": ...,
        "round": 12,
        "atk_max_hp": 500000,
        "def_max_hp": 300000,
        "atk_hp": 320000,
        "def_hp": 180000,
        "atk_units": {"401": 700, "411": 250},
        "def_units": {"401": 300}
      }
      ↓
[4] 이후 BattleWorker가 매 틱 battle_tick binary를 관전자에게도 전송
```

> 스냅샷이 필요한 이유: 관전자는 중간 참여이므로 `atk_max_hp` 등 초기값을 알 수 없음.
> HP 바 렌더링(`hp / max_hp`)이 불가능하므로 join 시 현재 전체 상태를 1회 제공.

#### BattleWorker 전송 순서

```
binary tick 생성 후:
  1. send_bytes(attacker_no, data)
  2. send_bytes(defender_no, data)
  3. subscribers = SMEMBERS battle_subscribers:{battle_id}
     for sub in subscribers:
         send_bytes(sub, data)        ← 동일 binary 재사용 (재직렬화 없음)
```

> binary는 이미 pack된 bytes 객체 → N명에게 재사용 전송. 직렬화 비용은 1회.

#### 관전 종료 조건

| 조건 | 처리 |
|------|------|
| 클라이언트 `battle_unwatch` 호출 (API 9041) | `SREM battle_subscribers:{battle_id} {user_no}` |
| WebSocket 연결 종료 | disconnect 핸들러에서 해당 user_no를 모든 구독에서 제거 |
| 전투 종료 (`battle_end`) | `DEL battle_subscribers:{battle_id}` |

#### 관전 제한

- 1인당 동시 관전 가능 배틀: 1개 (전투 화면은 1개만 열 수 있음)
- 배틀당 최대 관전자: 제한 없음 (binary 재사용으로 추가 비용 미미)

---

## 14. Background Workers

| Worker | 주기 | 역할 |
|--------|------|------|
| `TaskWorker` | 상시 | march 도착/귀환, NPC 리스폰, 집결 도착 처리 |
| `BattleWorker` | 1초 틱 | battle:active 순회, 라운드 계산, WS push, **전장 집계 틱 전송** |

---

## 15. 전장(Battlefield) 시스템

### 개요

```
전장 1 / 2 / 3: 독립적인 100×100 세계 맵 인스턴스
참여(member)   = 내 성을 해당 전장에 투입 (1인 1전장)
관전(subscriber) = 전장 집계 틱 수신 (참여하지 않은 전장도 관전 가능)
```

### 플로우

```
[참여]
클라이언트: battlefield_join(bf_id=2)
  → BattlefieldManager: 중복 참여 체크 → Redis bf_join → DB join_battlefield
  → 기존 구독자에게 battlefield_join 이벤트 전송

[관전]
클라이언트: battlefield_watch(bf_id=1)
  → BattlefieldManager: Redis bf_watch 구독 등록
  → 현재 전장 스냅샷 응답 (members 위치 + 진행 중 전투 목록)
  → 이후 BattleWorker가 매 1초 battlefield_tick 전송

[후퇴]
클라이언트: battlefield_retreat()
  → BattlefieldManager: Redis bf_retreat → DB retreat_battlefield
  → 잔여 구독자에게 battlefield_retreat 이벤트 전송
```

### battlefield_tick 포맷

```json
{
  "type": "battlefield_tick",
  "bf_id": 1,
  "battles": [
    [battle_id, x, y, atk_hp_pct, def_hp_pct, round_no],
    [battle_id, x, y, atk_hp_pct, def_hp_pct, round_no]
  ]
}
```

- `atk_hp_pct` / `def_hp_pct`: 0~100 정수 (HP 백분율)
- 전투가 없으면 `battles: []` 또는 틱 자체가 전송되지 않음
- 수신자: `battlefield:{bf_id}:subscribers` (멤버 + 외부 관전자 포함)

### battlefield_info 스냅샷 (9053 / 9054 공통 응답)

```json
{
  "bf_id": 1,
  "members": {
    "101": {"castle_x": 45, "castle_y": 23, "joined_at": "2026-03-03T..."},
    "202": {"castle_x": 12, "castle_y": 8, "joined_at": "2026-03-03T..."}
  },
  "battles": [
    {"battle_id": 5, "x": 45, "y": 23, "atk_hp_pct": 75, "def_hp_pct": 60,
     "round": 5, "attacker_no": 101, "defender_no": 202}
  ]
}
```

### 전투 ↔ 전장 연동

전장 내에서 발생한 전투는 `battle:{battle_id}` Hash에 다음 필드가 추가로 저장됨:

| 필드 | 값 | 용도 |
|------|-----|------|
| `bf_id` | int (0=비전장) | 전장 내 전투 여부 |
| `to_x` / `to_y` | int | 전투 발생 좌표 (battlefield_tick 렌더링용) |
| `atk_hp` / `def_hp` | int | 매 틱 갱신 (battlefield_tick HP 계산용) |

전투 종료 시 `bf_remove_battle(bf_id, battle_id)` 자동 처리.

### battlefield_list 응답 (9050)

```json
{
  "success": true,
  "data": {
    "battlefields": [
      {"bf_id": 1, "member_count": 12, "subscriber_count": 17},
      {"bf_id": 2, "member_count": 8,  "subscriber_count": 10},
      {"bf_id": 3, "member_count": 0,  "subscriber_count": 0}
    ]
  }
}
```

- `member_count`: 성을 투입한 참여자 수
- `subscriber_count`: `battlefield_tick` 수신 중인 전체 구독자 수 (참여자 포함)
- 외부 관전자 수 = `subscriber_count - member_count`

---

### 클라이언트 UI (battlefield.html)

#### 전장 목록 섹션

전장 1~3을 카드 형태로 나열. 각 카드에 표시:

| 항목 | 내용 |
|------|------|
| 전장 번호 | bf_id (1 / 2 / 3) |
| 참여 수 | `참여 N명` (member_count) |
| 관전 수 | `관전 N명` (subscriber_count, 참여자 포함) |
| 참여 버튼 | 내가 이 전장 참여 중 → `[후퇴]` / 미참여 → `[참여]` |
| 관전 버튼 | 이 전장 관전(구독) 중 → `[관전 종료]` / 미구독 → `[관전]` |
| 선택 효과 | 클릭 시 아래 전장 맵이 해당 bf_id로 전환 |

#### 전장 맵 섹션

```
캔버스 600×600 (세계 맵과 동일 스케일, 100×100 격자)
  ● 파란 원   = 참여자 성 위치 (castle_x, castle_y)
  ● 빨간 원   = 진행 중 전투 위치 (클릭 시 HP% 툴팁)
  숫자 표시    = user_no (성 옆) / HP%(공/수) (전투 원 옆)
  범례: 🔵성 / 🔴전투중
```

#### 클라이언트 상태 변수

```javascript
let currentBfId    = null;  // 현재 선택(보고 있는) 전장 bf_id
let myBfId         = null;  // 내가 성을 투입한 bf_id (없으면 null)
let watchingBfId   = null;  // 현재 구독 중인 bf_id (없으면 null)
let bfSnapshot     = null;  // 현재 전장 스냅샷 {members, battles}
let bfBattles      = {};    // {battle_id: [x, y, atk_pct, def_pct, round]}
let bfList         = [];    // 전장 목록 [{bf_id, member_count, subscriber_count}]
```

#### WS 이벤트 → 클라이언트 처리

| 이벤트 | 처리 |
|--------|------|
| `battlefield_tick` | `bfBattles` 갱신 → 맵 재렌더링 (현재 선택된 bf_id에 한함) |
| `battlefield_join` | `bfSnapshot.members`에 신규 성 추가 → 맵 재렌더링 + 참여 수 +1 |
| `battlefield_retreat` | `bfSnapshot.members`에서 성 제거 → 맵 재렌더링 + 참여 수 -1 |

#### main.html WS 전달 추가

```javascript
// handleWebSocketMessage() switch 추가 항목
case 'battlefield_tick':
case 'battlefield_join':
case 'battlefield_retreat':
    forwardToBattlefieldFrame({ type: message.type, data: message.data });
    break;
```

---

### DB 테이블

```sql
CREATE TABLE battlefield_members (
    id        INT PRIMARY KEY AUTO_INCREMENT,
    bf_id     TINYINT NOT NULL,
    user_no   INT NOT NULL,
    castle_x  INT NOT NULL,
    castle_y  INT NOT NULL,
    joined_at DATETIME NOT NULL,
    UNIQUE KEY uq_user (user_no),
    INDEX idx_bf (bf_id)
);
```

---

## 16. Python → C++ 포팅 계획 ⬜

### 교체 대상

```python
# services/game/battle_calc.py (Python 현재)
def calculate_round(attacker_units, defender_units,
                    attacker_hero, defender_hero, round_no):
    ...

# cpp/battle_calc.cpp → pybind11 → battle_calc_cpp.so
# 동일 입출력 인터페이스, 속도만 다름
# Game Layer 코드 변경 최소화
```

### 벤치마크 계획

```
시나리오: N개 동시 전투, 1초 틱
측정: 틱 1회 처리 시간 (ms)
N = 10, 50, 100, 500

예상:
  Python: N=100 이상에서 1초 내 처리 한계
  C++:    N=10,000+ 수준까지 처리 가능
```

---

## 16. 미결 사항

| 항목 | 내용 |
|------|------|
| 성 공격 max_rounds | 현재 50 — 멀티 공격자 환경 재검토 필요 |
| 약탈 수송 용량 | 병력 수 기반 상한 여부 미결정 |
| 다중 공격자 약탈 분배 | 기여도 비례? 동등 분배? |
| 집결 동시 참여 제한 | 플레이어당 동시 집결 참여 가능 수 |
| 집결 취소 규칙 | Leader 취소 시 이동 중인 rally_gather 병력 처리 |
| 병종 상성 수치 | 계수 1.5× 확정 여부 |
| NPC 집결 EXP 분배 | 참여자 간 EXP 배분 방식 |
| 거점 점령 로직 | 점령 시간, 연맹 귀속, 거점 버프 효과 |
