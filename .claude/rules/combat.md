---
paths:
  - "fastapi/services/game/BattleManager.py"
  - "fastapi/services/game/MarchManager.py"
  - "fastapi/services/game/MapManager.py"
---

# 전투 시스템 변경 규칙

## 이 파일 수정 전 반드시 읽어야 할 파일
- `.claude/docs/COMBAT.md` — 전투/행군/맵 시스템 전체 설계

## 고도 개발 분류
전투/행군 관련 로직 변경은 **항상 고도 개발**로 분류한다.
Step 4 고도 개발 검증(정합성 테스트 + 부하 시나리오 분석)을 반드시 적용한다.

## 전투 시스템 주의사항
- 전투 전/후 병력 수 무결성 검증 필수
- 전투 중 지원군 합류 시나리오 검증
- Worker 업데이트 타이밍 간섭 확인 (TaskWorker와 Game Manager 동시 접근)
- 버프 적용 순서 및 타이밍 검증
- 다수 유저 동시 전투 시 Redis 경합 지점 분석
