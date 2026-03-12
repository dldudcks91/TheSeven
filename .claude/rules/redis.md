---
paths:
  - "fastapi/services/redis_manager/**"
  - "fastapi/services/background_workers/**"
---

# Redis / Worker 변경 규칙

## 이 파일 수정 전 반드시 읽어야 할 파일
- `fastapi/services/redis_manager/` — 전체 키 사용 현황
- `fastapi/services/background_workers/` — SyncWorker, TaskWorker 로직
- `fastapi/main.py` — startup_event, worker 등록 구조

## Redis 키 네이밍 (상세)

| 용도 | 키 패턴 | 타입 |
|------|---------|------|
| 유저 데이터 캐시 | `user_data:{user_no}:{category}` | Hash |
| Dirty flag | `sync_pending:{category}` | Set (member = user_no) |
| Task 완료 큐 | `completion_queue:{task_type}` | Sorted Set (score = timestamp) |
| Task 메타데이터 | `completion_queue:{task_type}:metadata:{member}` | String/Hash |

## 동기화 체크리스트
- [ ] 쓰기 작업 후 dirty flag(`sync_pending:{category}`) 설정
- [ ] Task 등록 시 `completion_queue:{task_type}` + metadata 쌍으로 처리
- [ ] Redis 키 만료(TTL) 설정이 필요한 경우 명시
- [ ] 기존 키를 사용하는 다른 로직 영향 확인

## Worker 수정 시 주의사항
- Worker 예외 발생 시 서버 중단 금지 — 로깅 후 다음 사이클로 진행
- `main.py` startup_event에 Worker 등록 여부 확인
- 동시성 문제 발생 가능 구간: 원자적 연산(`MULTI/EXEC`, Lua 스크립트) 사용
- Connection Pool max 50 한계 고려
