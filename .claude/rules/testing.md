---
paths:
  - "fastapi/tests/**"
---

# 테스트 작성 규칙

## 테스트 인프라

| 컴포넌트 | 테스트 환경 |
|----------|-----------|
| DB | `theseven_test` (MySQL, 테스트 간 DELETE로 초기화) |
| Redis | `fakeredis` (인메모리, 외부 Redis 불필요) |
| HTTP Client | `httpx.AsyncClient` + `ASGITransport` (서버 실행 불필요) |
| Background Workers | 미실행 (startup 이벤트 비활성화) |
| CSV 메타데이터 | `GameDataManager.initialize()` 세션 1회 로드 |

**실행**: `cd fastapi && python -m pytest tests/ -v`

## 이 디렉토리 수정 전 반드시 읽어야 할 파일
- `fastapi/tests/conftest.py` — fixture 구조, DB/Redis 초기화 방식

## 테스트 작성 원칙
- 정상 흐름 + 실패 흐름(success: false) 모두 작성
- 새 도메인은 `tests/test_{domain}.py` 파일 생성
- 기존 테스트 회귀 확인 필수 (전체 스위트 실행)
- Background Worker는 직접 함수 호출로 테스트 (HTTP 경유 불필요)
