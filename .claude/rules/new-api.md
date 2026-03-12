---
paths:
  - "fastapi/services/system/api_manager.py"
---

# 신규 API 추가 규칙

## 이 파일 수정 전 반드시 읽어야 할 파일
- `.claude/docs/API.md` — 기존 api_code 충돌 방지, 현재 구현 현황 파악

## API 코드 체계

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

새 API 추가 시 기존 범위 체계를 따른다. 새 도메인이 필요하면 Human Review에서 범위 결정.

## 신규 Game Manager 추가 패턴

1. `services/game/{domain}_manager.py` 생성
2. `__init__(self, db_manager, redis_manager)` 생성자 패턴 유지
3. `services/system/api_manager.py`의 라우팅 테이블에 `api_code → (ManagerClass, "method_name")` 등록
4. `.claude/docs/API.md`에 명세 추가
5. 필요 시 `services/background_workers/`에 Worker 로직 추가

## 체크리스트
- [ ] 기존 api_code 충돌 없음 (API.md 확인)
- [ ] api_code 범위 체계 준수
- [ ] 라우팅 테이블 등록 완료
- [ ] `.claude/docs/API.md` 명세 추가 완료
- [ ] 응답 형식 공통 구조(success, message, data) 준수
