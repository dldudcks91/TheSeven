---
paths:
  - "fastapi/models.py"
  - "fastapi/services/db_manager/**"
---

# DB 스키마 변경 규칙

## 이 파일 수정 전 반드시 읽어야 할 파일
- `fastapi/models.py` — 현재 스키마 기준 파악
- `fastapi/services/db_manager/` — 전체 DB 접근 레이어 현황

## 핵심 원칙
- `models.py`가 스키마의 기준이다. DB와 불일치 발견 시 불일치 보고 후 수정 방향 제안
- Game Manager에서 DB 직접 쓰기 금지 — 반드시 Redis 경유
- DB 직접 삽입이 필요한 경우(건물 최초 생성 등)에만 허용, 이 경우 Redis에도 반드시 동기화

## 체크리스트
- [ ] models.py 변경 시 db_manager/ 관련 쿼리 영향 확인
- [ ] DB 직접 삽입 후 Redis 동기화 처리
- [ ] SQLAlchemy ORM 사용 (raw query 금지)
- [ ] async 세션 사용 (`async with db.begin()`)
- [ ] 새 테이블/컬럼 추가 시 마이그레이션 계획 포함
