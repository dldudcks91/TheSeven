# CLIENT.md - 클라이언트 기술 문서

> **프로젝트**: TheSeven 클라이언트
> **최종 수정**: 2026-03-01

---

## 1. 개요

- **기술**: 순수 HTML + JavaScript (프레임워크 없음)
- **구조**: `main.html` 기반의 **iframe 모듈 시스템**
- **통신**: `fetch` (REST API) + `WebSocket` (실시간 알림)
- **상태 관리**: 각 iframe이 독립적으로 서버 API를 직접 호출하여 데이터를 관리

---

## 2. 페이지 구조

### 2.1 전체 레이아웃 (main.html)

```
┌─────────────────────────────────────────────────┐
│ 헤더: 플레이어 ID 입력 | 전체 데이터 로드 | 현재 시각 │
├─────────────────────────────────────────────────┤
│ 탭: [API 테스트] [게임] [영웅] [연맹]              │
├─────────────────────────────────────────────────┤
│ 자원 바: <resource.html iframe> | <buff.html>    │
├─────────────────────────────────────────────────┤
│                                                 │
│           탭별 콘텐츠 (iframe 그리드)              │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 2.2 탭 구성

| 탭 ID | 탭명 | 내용 |
|-------|------|------|
| api | API 테스트 | 직접 API 코드 호출 테스트용 (개발/디버깅) |
| game | 게임 | 6개 iframe 2×3 그리드 |
| hero | 영웅 | 미구현 (탭만 존재) |
| ally | 연맹 | alliance.html iframe 1개 |

### 2.3 게임 탭 iframe 배치

```
┌────────────────┬────────────────┐
│  building.html │  research.html │  ← 건물, 연구
├────────────────┼────────────────┤
│    unit.html   │   item.html    │  ← 유닛, 아이템
├────────────────┼────────────────┤
│  mission.html  │   shop.html    │  ← 미션, 상점
└────────────────┴────────────────┘
```

---

## 3. iframe ID 목록

| iframe ID | src | 역할 |
|-----------|-----|------|
| resourceFrame | resource.html | 자원 현황 상단 바 (항상 표시) |
| buffFrame | buff.html | 버프 아이콘 상단 바 (항상 표시) |
| buildingFrame | building.html | 건물 건설/업그레이드 |
| researchFrame | research.html | 연구 트리 |
| unitFrame | unit.html | 유닛 훈련/업그레이드 |
| itemFrame | item.html | 아이템 인벤토리 |
| missionFrame | mission.html | 미션/퀘스트 목록 |
| shopFrame | shop.html | 상점 |
| allyFrame | alliance.html | 연맹 관리 |

---

## 4. 데이터 로드 흐름

### 4.1 초기화 시퀀스

```
1. 페이지 로드 (window.onload)
   └─ GameConfigManager.loadGameConfig()
       └─ POST /api { api_code: 1002 }  → 게임 설정 데이터 메모리 캐싱

2. 유저가 "전체 데이터 로드" 버튼 클릭
   ├─ POST /api { api_code: 1010 }  → 서버 Redis 캐시 프리로드 (LoginManager)
   ├─ WebSocket 연결 ws://{host}/ws/{userId}
   └─ 모든 iframe에 postMessage { type: 'set_player_id', userId }
       └─ 각 iframe이 자체 API 호출로 데이터 로드
```

### 4.2 플레이어 ID 관리

- 헤더의 `globalUserId` input에 수동 입력
- "전체 데이터 로드" 버튼 클릭 시에만 모든 iframe에 전파 (자동 전파 없음)
- 각 iframe은 `currentUserId` 변수로 로컬 관리

---

## 5. postMessage 이벤트 시스템

### 5.1 main.html → 각 iframe (발신)

| type | 데이터 | 설명 | 수신 대상 |
|------|--------|------|---------|
| `set_player_id` | `{ userId: int }` | 플레이어 ID 전달 (초기화) | 모든 iframe |
| `refresh_items` | 없음 | 아이템 목록 새로고침 요청 | itemFrame |
| `update_mission_ui` | `{ payload: mission_data }` | 미션 UI 업데이트 | missionFrame |
| `response_config` | `{ payload: config_data }` | 게임 설정 데이터 응답 | 요청한 iframe |

### 5.2 각 iframe → main.html (수신)

| type | 데이터 | 설명 | 발신 주체 |
|------|--------|------|---------|
| `request_config` | `{ configType: string }` | 게임 설정 데이터 요청 | 모든 iframe |
| `refresh_item` | 없음 | 아이템 새로고침 요청 | 아이템을 지급하는 iframe |
| `update_mission` | `{ payload: mission_data }` | 미션 진행도 업데이트 | 게임 액션 iframe |
| `refresh_resource` | 없음 | 자원 새로고침 요청 | alliance.html 등 |

### 5.3 WebSocket → main.html (서버 → 클라이언트)

| type | 데이터 | 처리 |
|------|--------|------|
| `connected` | `{ user_no }` | 연결 확인 로그 |
| `unit_finish` | `{ data: { unit, mission_update } }` | unitFrame에 포워딩 + 토스트 알림 |

---

## 6. 각 iframe의 공통 패턴

### 6.1 API 호출 (공통 함수)

모든 iframe에서 동일한 `apiCall` 패턴을 사용:

```javascript
async function apiCall(apiCode, data = {}) {
    const uid = getUserNo();
    if (!uid) return null;
    try {
        const res = await fetch('/api', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_no: uid, api_code: apiCode, data })
        });
        return await res.json();
    } catch (e) {
        return { success: false, message: e.message };
    }
}
```

### 6.2 플레이어 ID 수신 (공통 패턴)

```javascript
// 모든 iframe에서 공통
window.addEventListener('message', async function(event) {
    if (event.data && event.data.type === 'set_player_id') {
        const newId = parseInt(event.data.userId);
        if (currentUserId !== newId) {
            currentUserId = newId;
            await loadData();  // iframe별 데이터 로드 함수 호출
        }
    }
});
```

### 6.3 게임 설정 요청 (공통 패턴)

```javascript
// iframe에서 게임 설정 데이터 필요 시
function requestConfig(configType) {
    return new Promise((resolve) => {
        window.parent.postMessage({ type: 'request_config', configType }, '*');
        window.addEventListener('message', function handler(e) {
            if (e.data?.type === 'response_config') {
                window.removeEventListener('message', handler);
                resolve(e.data.payload);
            }
        });
    });
}
```

---

## 7. GameConfigManager (gameConfigManager.js)

### 7.1 역할

- 서버의 게임 밸런스 데이터(CSV 기반)를 클라이언트에서 캐싱
- API 1002 (`GAME_CONFIG_ALL`) 호출로 전체 설정 메모리 로드

### 7.2 사용법

```javascript
// 싱글톤 패턴
const manager = GameConfigManager.getInstance();
const config = await manager.loadGameConfig();
// config 구조: { building: {...}, unit: {...}, research: {...}, ... }
```

### 7.3 설정 데이터 구조 (API 1002 응답)

```json
{
    "building": { "201": { "1": { "cost": {...}, "time": 20 }, ... } },
    "unit":     { "401": { "tier": 1, "stats": {...} }, ... },
    "research": { "1001": { "1": { "cost": {...}, "buff_idx": 101 }, ... } },
    "buff":     { "101": { "effect_type": "buff", ... } },
    "item":     { "21001": { "category": "resource", "value": 1000 }, ... }
}
```

---

## 8. WebSocket 연결

### 8.1 연결 URL

```
ws://{host}/ws/{user_no}
```

### 8.2 자동 재연결

```javascript
WS_MAX_RECONNECT = 5     // 최대 재연결 시도
WS_RECONNECT_DELAY = 3000  // 재연결 대기 (3초)
```

### 8.3 메시지 처리 흐름

```
서버 TaskWorker가 게임 작업 완료 감지
    ↓
WebSocket.send(user_no, message)
    ↓
main.html handleWebSocketMessage(message)
    ↓
message.type에 따라:
├─ 'unit_finish'  → unitFrame.postMessage({ type: 'update_unit_ui' })
│                 → missionFrame.postMessage({ type: 'update_mission_ui' })
│                 → showToast('유닛 훈련 완료!')
└─ 'connected'   → 연결 확인 로그
```

---

## 9. 토스트 알림 시스템

### 9.1 사용법

```javascript
showToast(message, type, title);
// type: 'success' | 'error' | 'warning' | 'info'
// 5초 후 자동 제거
```

### 9.2 토스트 스타일

| type | 색상 | 기본 타이틀 |
|------|------|-----------|
| success | 초록 (#28a745) | 성공 |
| error | 빨강 (#dc3545) | 오류 |
| warning | 노랑 (#ffc107) | 경고 |
| info | 파랑 (#17a2b8) | 알림 |

---

## 10. 페이지별 역할

| 파일명 | API 코드 | 주요 기능 |
|--------|---------|---------|
| main.html | 1010, 1002 | 메인 컨테이너, WebSocket, 설정 로드 |
| resource.html | 1011 | 자원 현황 표시 (상단 바) |
| buff.html | 1012 | 버프 현황 표시 (상단 바 아이콘) |
| building.html | 2001~2006 | 건물 목록, 건설/업그레이드/취소 |
| research.html | 3001~3004 | 연구 트리, 연구 시작/취소 |
| unit.html | 4001~4003 | 유닛 목록, 훈련/업그레이드 |
| item.html | 6001~6003 | 아이템 인벤토리, 아이템 사용 |
| mission.html | 5001~5002 | 미션 목록, 보상 수령 |
| shop.html | 6011~6013 | 상점 진열, 새로고침, 구매 |
| alliance.html | 7001~7017 | 연맹 전체 관리 (상세는 아래) |

---

## 11. alliance.html 구조

연맹 화면은 단일 iframe으로 표시되며 2열 3행 카드 레이아웃으로 구성:

```
┌──────────────┬──────────────┐
│   연맹 정보   │   공지사항   │  ← 220px
├──────────────┼──────────────┤
│   연맹 연구   │   멤버목록   │  ← 275px
├──────────────┼──────────────┤
│   연맹 검색   │   연맹관리   │  ← 220px
└──────────────┴──────────────┘
```

**권한별 UI 분기**:
- 일반 멤버: 연맹관리 카드 → "권한이 없습니다" 표시
- 간부(3+): 연맹관리 카드 → 가입신청 목록 + 연구 추천/시작 버튼
- 맹주(1): 연맹관리 카드 → 가입방식 변경 + 해산 + 가입신청 목록

---

## 12. 개발 시 주의사항

### 12.1 플레이어 ID 관리

- iframe은 `currentUserId` 변수로 관리
- `getUserNo()`는 `currentUserId` 우선, 없으면 `window.parent.currentUserId` fallback
- **"전체 데이터 로드" 없이는 iframe에 ID가 전달되지 않음**

### 12.2 동일 출처 (Same-Origin)

- 모든 iframe이 같은 서버에서 서빙되므로 `postMessage` origin 검증 불필요
- `event.source.postMessage(data, '*')` 패턴 사용

### 12.3 iframe 간 직접 통신 금지

- iframe끼리 직접 통신하지 않음
- 반드시 `main.html`을 중계 허브로 사용

### 12.4 새 iframe 추가 시 체크리스트

- [ ] `main.html`의 `frameIds` 배열에 ID 추가 (`set_player_id` 자동 전파용)
- [ ] `window.addEventListener('message', ...)` 에서 `set_player_id` 수신 처리
- [ ] `getUserNo()` 함수 구현 (공통 패턴)
- [ ] `apiCall()` 함수 구현 (공통 패턴)
- [ ] `routers/pages.py`에 라우터 등록
