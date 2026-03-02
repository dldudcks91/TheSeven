# COMBAT.md - 전투 시스템 기획 & 설계 문서

> **프로젝트**: TheSeven
> **최종 수정**: 2026-03-03
> **상태**: 구현 완료 (Python 1차)

---

## 1. 시스템 개요

```
[이동 Phase]          [전투 Phase]          [종료 Phase]
출진 선언              도착 → 전투 시작        전투 종료 판정
    ↓                      ↓                      ↓
completion_queue:march  battle:active Set      약탈 / 유닛 손실
(기존 TaskWorker 패턴)  BattleWorker 1초 틱     귀환 큐 등록
    ↓                      ↓                      ↓
도착 감지              라운드별 계산           completion_queue:march_return
→ battle_start()      WebSocket push          → 귀환 처리
```

### 1.1 확정 사항

| 항목 | 결정값 |
|------|--------|
| 동시 행군 수 (플레이어당) | 최대 3개 |
| 맵 방식 | 자유 좌표 (랜덤 배치) |
| 오프라인 공격 | 허용 |
| 오프라인 수비 | 주둔 병력 자동 방어 |
| 전투 방식 | 라운드형 (1라운드 = 1초) |
| 구현 언어 | Python 1차 → C++ 교체 벤치마크 |

### 1.2 확정된 설계 사항

| 항목 | 결정값 |
|------|--------|
| 맵 크기 | **100 × 100** (좌표 0~99) |
| 최대 라운드 | **50 라운드** (50초) |
| 약탈 비율 | **수비자 자원의 20%** |
| 약탈 상한 | 없음 (포트폴리오 단순화) |
| 부상병 처리 | **즉시 death** 상태 (포트폴리오 단순화) |
| 행군 취소 | **즉시 귀환** (유닛 field→ready 복귀) |
| 행군 속도 | **unit.speed × 10 타일/분** (보병=20, 기병=30, 궁병=10) |

---

## 2. 맵 시스템

### 2.1 좌표 체계

- **맵 크기**: 100 × 100 (좌표 0 ~ 99)
- **성 배치**: 계정 생성 시 서버가 랜덤 좌표 배정 (기존 점유 좌표 제외)
- **이동 거리**: 유클리드 거리 `sqrt((dx)² + (dy)²)`
- **이동 시간**: `거리 / march_speed` (초 단위)

### 2.2 DB 스키마 변경 — StatNation 컬럼 추가

현재 `StatNation`에 좌표 없음. 다음 2개 컬럼 추가 필요:

```python
# models.py StatNation에 추가
map_x: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
map_y: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```

> **대안 검토**: 별도 `Castle` 테이블 vs StatNation 컬럼 추가
> → StatNation이 플레이어 기본 정보 테이블이므로 **컬럼 추가 채택** (성은 1인 1개)

### 2.3 Redis 맵 캐시

```
map:positions → Hash
  key:   user_no (str)
  value: "x,y"  예: "127,453"
```

- 서버 시작 시 DB에서 전체 로드
- 성 생성 시 즉시 업데이트

### 2.4 주변 플레이어 조회 (Nearby Query)

**포트폴리오 구현**: 전체 스캔 O(N)
```python
# map:positions Hash 전체 읽기 → 거리 계산 → 반경 이내 필터
```

**프로덕션 확장 방향 (언급용)**:
```
Redis GEOADD / GEORADIUS → O(N + log M)
```

---

## 3. 행군 시스템

### 3.1 행군 흐름

```
march_create() 호출
  → 보유 행군 수 체크 (최대 3)
  → 출진 가능 유닛 수 체크 (ready 상태)
  → 이동 시간 계산
  → 유닛 상태 변경: ready → field
  → DB: March 레코드 생성
  → Redis: completion_queue:march 등록 (score = 도착 timestamp)
  → Redis: user_data:{user_no}:marches 업데이트

TaskWorker (기존 패턴, 주기적 실행)
  → completion_queue:march에서 만료된 march 감지
  → battle_start() 호출
```

### 3.2 새 DB 테이블: March

```python
class March(Base):
    __tablename__ = 'march'

    march_id: int        # PK, auto increment
    user_no: int         # 공격자
    target_user_no: int  # 수비자
    from_x: int
    from_y: int
    to_x: int
    to_y: int
    units: str           # JSON {"401": 100, "411": 50}
    hero_idx: int        # nullable (영웅 동행 시)
    march_speed: float   # 좌표/초
    departure_time: datetime
    arrival_time: datetime
    return_time: datetime    # nullable (귀환 완료 예정 시각)
    status: str          # marching / battling / returning / completed / cancelled
    battle_id: int       # nullable (전투 시작 후 연결)
```

### 3.3 Redis 행군 데이터

```
completion_queue:march → Sorted Set
  member: march_id
  score:  arrival_time (UTC timestamp)

user_data:{user_no}:marches → Set
  member: march_id  (활성 행군 ID 목록, 수 제한 체크용)

march:{march_id} → Hash
  (행군 상세 데이터, 전투 중 조회용)
```

### 3.4 행군 취소

- **marching 상태**에서만 취소 가능
- 유닛 즉시 귀환 (`field` → `ready`)
- `completion_queue:march`에서 제거
- March status → `cancelled`

### 3.5 API 코드 (행군)

| API Code | 메서드명 | 설명 |
|----------|---------|------|
| 9001 | `my_position` | 내 성 위치 조회 |
| 9002 | `map_info` | 맵 조회 (주변 플레이어/NPC 목록) |
| 9003 | `npc_list` | NPC 목록 조회 |
| 9011 | `march_list` | 내 행군 목록 조회 |
| 9012 | `march_create` | 출진 (target_type: user/npc, 유닛 수, 영웅 선택) |
| 9013 | `march_cancel` | 행군 취소 (marching 상태만) |

---

## 4. 전투 시스템

### 4.1 전투 시작 조건

```
TaskWorker가 march 도착 감지
  ↓
수비자 주둔 병력 조회 (ready 상태 유닛)
  ↓
주둔 병력 0명?
  → YES: 무혈입성 (전투 없이 약탈)
  → NO:  Battle 생성 → BattleWorker에 등록
```

### 4.2 전투 상태 (Redis)

```
battle:{battle_id} → Hash
  battle_id
  attacker_user_no
  defender_user_no
  march_id

  # 공격자 상태
  attacker_hp          # 현재 HP
  attacker_max_hp      # 최대 HP
  attacker_units       # JSON {"401": 100, "411": 50}

  # 수비자 상태
  defender_hp
  defender_max_hp
  defender_units       # JSON (주둔 병력 스냅샷)

  # 전투 진행
  round                # 현재 라운드
  max_rounds           # 최대 라운드 (50 예정)
  start_time
  status               # ongoing / attacker_win / defender_win / draw

battle:active → Set
  member: battle_id    (BattleWorker가 이 Set을 순회)
```

### 4.3 HP 계산

```
최대 HP = Σ(유닛 종류별) { unit_health(CSV) × 유닛 수 }

예시:
  보병 100명 × health 100 = 10,000
  기병 50명  × health 100 =  5,000
  → 총 HP: 15,000
```

### 4.4 라운드 계산 (calculate_round) ← C++ 교체 대상

```python
def calculate_round(attacker_units, defender_units,
                    attacker_hero=None, defender_hero=None,
                    round_no=0):
    """
    Returns:
        atk_damage: 공격자가 수비자에게 입히는 데미지
        def_damage: 수비자가 공격자에게 입히는 데미지
        skill_log:  발동된 스킬 설명 (있으면)
    """
    # 1. 기본 공격력 합산
    atk_power = Σ { unit_attack(CSV) × unit_count }
    def_power = Σ { unit_attack(CSV) × unit_count }

    # 2. 영웅 보정 (영웅 동행 시)
    if attacker_hero:
        atk_power *= (1 + attacker_hero.lv * 0.05)
    if defender_hero:
        def_power *= (1 + defender_hero.lv * 0.05)

    # 3. 방어력 적용
    # (방어력은 데미지 감소율로, GDD 전투 설계 확정 시 공식 결정)
    # 예: 데미지 = 공격력 × max(1 - 방어율, 0.1)

    # 4. 스킬 판정 (Hero 스킬 시스템 설계 후 추가)

    return atk_damage, def_damage, skill_log
```

**C++ 교체 계획**:
- `calculate_round()` 함수만 추출
- pybind11 또는 ctypes로 바인딩
- 벤치마크: Python vs C++, N개 동시 전투 기준 처리량(ticks/sec) 비교

### 4.5 전투 종료 조건

| 조건 | 결과 |
|------|------|
| 수비자 HP ≤ 0 | 공격자 승리 → 약탈 → 귀환 |
| 공격자 HP ≤ 0 | 수비자 승리 → 공격자 패패 귀환 |
| max_rounds 초과 | 무승부 → 공격자 자동 퇴각 |

### 4.6 BattleWorker (신규 Worker)

```python
# 기존 background_workers에 추가
class BattleWorker:
    TICK_INTERVAL = 1.0  # 초

    async def run(self):
        while True:
            await self.process_all_battles()
            await asyncio.sleep(self.TICK_INTERVAL)

    async def process_all_battles(self):
        battle_ids = await redis.smembers('battle:active')
        for battle_id in battle_ids:
            await self.process_single_battle(battle_id)

    async def process_single_battle(self, battle_id):
        # 1. Redis에서 전투 상태 조회
        # 2. calculate_round() 호출
        # 3. HP 업데이트
        # 4. 종료 조건 체크
        # 5. WebSocket push (관전 클라이언트에게)
        # 6. 종료 시: battle_end() 처리
```

### 4.7 WebSocket 메시지 추가

```json
// 전투 진행 중 (매 1초)
{
  "type": "battle_tick",
  "data": {
    "battle_id": 1042,
    "round": 12,
    "attacker_hp": 8400,
    "attacker_max_hp": 15000,
    "defender_hp": 3100,
    "defender_max_hp": 10000,
    "attacker_unit_loss": 50,
    "defender_unit_loss": 120,
    "log": "R12: 공격 1,240 데미지"
  }
}

// 전투 종료
{
  "type": "battle_end",
  "data": {
    "battle_id": 1042,
    "result": "attacker_win",
    "loot": { "food": 5000, "wood": 2000, "gold": 800 },
    "attacker_loss": { "401": 45, "411": 12 },
    "defender_loss": { "401": 200 }
  }
}

// 전투 시작 알림 (수비자에게)
{
  "type": "battle_incoming",
  "data": {
    "battle_id": 1042,
    "attacker_name": "플레이어A",
    "estimated_arrival": "2026-03-01T12:34:56"
  }
}
```

---

## 5. 전투 결과 처리

### 5.1 약탈 계산 (공격자 승리 시)

```
약탈량 = min(
    수비자 각 자원 × 약탈_비율(20%),
    행군 병력 기반 수송 용량  ← TBD
)
```

- 약탈 자원: 공격자 Redis 자원에 즉시 추가
- 수비자 자원: Redis에서 즉시 차감

### 5.2 유닛 손실 계산

```
손실 유닛 수 = round(총 유닛 수 × (받은_데미지 / 최대_HP))

포트폴리오 단순화:
  손실 유닛 → death 상태 (즉시)
  (실제 게임: injured → healing → ready 단계 존재)
```

### 5.3 귀환 처리

```
전투 종료 → march 상태 'returning' 변경
  → return_time = now + 이동 시간 (도달 시간과 동일)
  → completion_queue:march_return 등록
  → TaskWorker 감지 → 유닛 field→ready 상태 복구
```

### 5.4 새 DB 테이블: Battle

```python
class Battle(Base):
    __tablename__ = 'battle'

    battle_id: int         # PK, auto increment
    march_id: int          # FK → march
    attacker_user_no: int
    defender_user_no: int
    start_time: datetime
    end_time: datetime     # nullable
    status: str            # ongoing / attacker_win / defender_win / draw
    total_rounds: int      # nullable (완료 시 기록)

    # 결과 요약 (JSON 컬럼)
    attacker_loss: str     # JSON {"401": 45, "411": 12}
    defender_loss: str     # JSON
    loot: str              # JSON {"food": 5000, ...}
```

> **Battle Report 상세 로그**: 50라운드 × 전투당 로그는 Redis에서 관리.
> 전투 종료 후 요약본만 DB 저장. 상세 로그는 Redis TTL(24시간) 보관.

---

## 6. 영웅 연동 (기본 설계)

### 6.1 현재 Hero 테이블

```python
# 기존 models.py
class Hero(Base):
    user_no: int     # PK
    hero_idx: int    # PK
    hero_lv: int
    exp: int
```

Hero 테이블이 최소 구조. 스킬 시스템은 별도 설계 필요.

### 6.2 전투 연동 방식

- 행군 시 영웅 1명 선택 동행 (optional)
- 영웅은 `hero_idx` + `hero_lv`만으로 전투 보정 적용 (단순 레벨 기반)
- **동일 영웅 중복 출전 불가**: `march_create` 시 활성 행군의 `hero_idx` 충돌 체크 → `"해당 영웅은 이미 출전 중입니다"`
- 스킬 시스템은 Hero DB 설계 확정 후 추가

### 6.3 영웅 스킬 설계 방향 (예정)

```
hero_skill.csv 추가 예정:
  hero_idx, skill_idx, trigger_type (round/hp_percent),
  trigger_value, effect_type (damage/buff), value
```

---

## 7. DB 스키마 변경 요약

| 변경 대상 | 종류 | 내용 |
|----------|------|------|
| `StatNation` | 컬럼 추가 | `map_x INT`, `map_y INT` |
| `March` | 신규 테이블 | 행군 레코드 |
| `Battle` | 신규 테이블 | 전투 레코드 |

> Hero 스킬, 부상병 회복 등은 추후 별도 설계.

---

## 8. Redis 키 구조 추가

| 키 | 타입 | 내용 |
|----|------|------|
| `map:positions` | Hash | `{user_no: "x,y"}` |
| `march:{march_id}` | Hash | 행군 상세 데이터 |
| `user_data:{user_no}:marches` | Set | 활성 행군 ID 목록 |
| `completion_queue:march` | Sorted Set | score = 도착 timestamp |
| `completion_queue:march_return` | Sorted Set | score = 귀환 timestamp |
| `battle:{battle_id}` | Hash | 실시간 전투 상태 |
| `battle:active` | Set | 진행 중 전투 ID 목록 |
| `battle:{battle_id}:log` | List | 라운드별 로그 (TTL 24h) |

---

## 9. NPC 사냥 시스템

### 9.1 개요

유저 대 유저 전투 외에, 맵에 배치된 NPC(야생 몬스터)를 공격해 경험치/자원을 획득하는 시스템.

### 9.2 NPC 배치

- **npc_info.csv**: npc_idx, korean_name, tier, exp_reward, units(JSON), respawn_minutes
- **초기화**: 서버 시작 시 `NpcManager.initialize()` → `map:npcs` Hash에 UUID 기반 NPC 생성
- **Redis 키**: `map:npcs` Hash (`npc_id → JSON`)

```json
{
  "npc_id": "uuid",
  "npc_idx": 101,
  "x": 20, "y": 80,
  "alive": true,
  "tier": 1,
  "korean_name": "고블린 부족",
  "exp_reward": 50,
  "units": {"401": 30}
}
```

### 9.3 NPC 전투 흐름

```
march_create(target_type="npc", npc_id=...)
  → NPC 생존 확인
  → 행군 생성 (March 레코드, target_type="npc", npc_id 기록)
  → completion_queue:march 등록

TaskWorker (도착 감지)
  → NPC 병력 읽기
  → battle_start() → BattleWorker에 등록

전투 종료 (공격자 승리)
  → NPC alive = false
  → 영웅 EXP 지급 (add_hero_exp() → 레벨업 체크)
  → completion_queue:npc_respawn 등록 (score = now + respawn_time)
  → TaskWorker 감지 → NPC alive = true (리스폰)
```

### 9.4 March 테이블 target_type 추가

```python
# March 테이블 컬럼
target_type: str  # "user" | "npc"
npc_id: str       # nullable — NPC 공격 시 UUID
```

### 9.5 API 코드 체계 (9xxx — 전투/맵 도메인)

| Code | 메서드 | 설명 |
|------|--------|------|
| 9001 | `my_position` | 내 성 좌표 조회 |
| 9002 | `map_info` | 주변 플레이어/NPC 목록 (맵 전체) |
| 9003 | `npc_list` | NPC 목록 조회 |
| 9011 | `march_list` | 내 행군 목록 조회 |
| 9012 | `march_create` | 출진 선언 (target_type: user/npc) |
| 9013 | `march_cancel` | 행군 취소 (marching 상태만) |
| 9021 | `battle_info` | 진행 중 전투 상태 조회 |
| 9022 | `battle_report` | 전투 결과 리포트 조회 |

---

## 10. Background Worker 변경 사항

| Worker | 변경 | 내용 |
|--------|------|------|
| `TaskWorker` | 확장 | `completion_queue:march` 감지 → `battle_start()` 연결 |
| `TaskWorker` | 확장 | `completion_queue:march_return` 감지 → 귀환 처리 |
| `TaskWorker` | 확장 | 도착/귀환 시 `map_march_update/complete` 전체 브로드캐스트 |
| `BattleWorker` | **신규** | 1초 틱, `battle:active` 순회, 전투 계산 + WS push |
| `BattleWorker` | 확장 | 전투 종료 시 `map_march_update {status: returning}` 전체 브로드캐스트 |

---

## 11. Python → C++ 비교 계획

### 교체 대상 함수

```python
# services/game/battle_calc.py (Python)
def calculate_round(attacker_units: dict, defender_units: dict,
                    attacker_hero: dict, defender_hero: dict,
                    round_no: int) -> tuple[int, int, str]:
    ...

# battle_calc.cpp → pybind11 → battle_calc_cpp.so (C++)
# 동일 인터페이스, 동일 결과, 속도만 다름
```

### 벤치마크 기준

```python
# 시나리오: N개 동시 전투, 1초 틱
# 측정: 1틱 처리에 걸리는 시간 (ms)
# N = 10, 50, 100, 500 케이스별 비교
```

### 예상 결과

- Python: N=100 이상에서 1초 틱 내 처리 한계
- C++: N=10,000+ 수준까지 처리 가능
- → 포트폴리오 벤치마크 결과로 수치 제시

---

## 12. 클라이언트 화면 구성 (battle.html)

```
┌──────────────────────────────────────────────────────┐
│  [맵] 현재 내 좌표: (127, 453) | 활성 행군: 2/3       │
├───────────────────────────────────────────────────────┤
│  주변 플레이어 목록           │  내 행군 현황          │
│  [플레이어A (200,300)] [공격] │  → 플레이어A 도착 47초 │
│  [플레이어B (150,400)] [공격] │  ← 귀환 중 (120초)    │
│  [플레이어C (90, 500)] [공격] │                       │
├───────────────────────────────────────────────────────┤
│  [전투 화면] battle_id: #1042  라운드 12/50           │
│  공격자 HP: [████████░░] 8,400 / 15,000              │
│  수비자 HP: [███░░░░░░░] 3,100 / 10,000              │
│  ─────────────────────────────────────────────────── │
│  R12: 공격 → 1,240 데미지                            │
│  R12: 수비 → 880 데미지                              │
│  R11: 영웅 스킬 발동! +500 추가 데미지               │
└──────────────────────────────────────────────────────┘
```

**iframe 추가 필요**: `battleFrame` → `battle.html`
- main.html `frameIds` 배열에 추가
- WebSocket `battle_tick` / `battle_end` / `battle_incoming` 처리

---

## 13. 구현 현황

```
✅ Phase 1: 맵 & 위치 시스템 (완료)
  ✅ StatNation에 map_x, map_y 컬럼 추가
  ✅ 계정 생성 시 랜덤 좌표 배정 (MapManager)
  ✅ map:positions Redis 캐시
  ✅ API 9001 (my_position), 9002 (map_info)

✅ Phase 2: 행군 시스템 (완료)
  ✅ March DB 테이블 생성 (target_type, npc_id 포함)
  ✅ march_list(9011), march_create(9012), march_cancel(9013)
  ✅ TaskWorker에 completion_queue:march/march_return 처리
  ✅ 유닛 상태 ready ↔ field 전환

✅ Phase 3: 전투 시스템 — Python 1차 (완료)
  ✅ Battle DB 테이블 생성
  ✅ battle_start() — 전투 초기화
  ✅ calculate_round() — Python 구현
  ✅ BattleWorker — 1초 틱
  ✅ 전투 종료 처리 (약탈, 유닛 손실, 귀환)
  ✅ WebSocket battle_tick / battle_end 메시지

✅ Phase 4: NPC 사냥 시스템 (완료)
  ✅ npc_info.csv 메타데이터
  ✅ NpcManager (초기화, 조회 9003)
  ✅ CombatRedisManager map:npcs 관리
  ✅ March target_type="npc" 지원
  ✅ NPC 처치 후 영웅 EXP 지급 + 레벨업
  ✅ completion_queue:npc_respawn (TaskWorker 처리)

✅ Phase 5: 클라이언트 battle.html (완료)
  ✅ 맵 Canvas (600×600) — 행군 실시간 애니메이션
  ✅ NPC 클릭 팝업 — 유닛/영웅 드롭다운 선택
  ✅ 행군 목록 / 전투 보고서
  ✅ WebSocket 실시간 로그

✅ Phase 5.1: 멀티플레이어 실시간 맵 동기화 (완료)
  ✅ WebSocket 브로드캐스트 — map_march_start / map_march_update / map_march_complete
  ✅ APIManager → ws_manager 의존성 주입 체인 완성
  ✅ MapManager.map_info() — all_marches 포함 (페이지 로드 초기 상태)
  ✅ globalMarches{} 클라이언트 딕셔너리 — 전체 유저 행군 실시간 관리
  ✅ 전투 종료 시 returning 상태 브로드캐스트 버그 수정 (BattleWorker)
  ✅ 영웅 중복 출전 방지 (MarchManager — 3개 분기 모두)

⬜ Phase 6: C++ 벤치마크 (예정)
  ⬜ calculate_round() C++ 재구현
  ⬜ pybind11 바인딩
  ⬜ 벤치마크 측정 & 비교 (Python vs C++)
```
