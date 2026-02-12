📂 /services/game/README.txt

==================================================
Core Game Domain Layer - Overview
==================================================

1. 개요 (Overview)
본 폴더는 게임의 '심장부'에 해당하는 도메인 로직 레이어입니다.
개별 매니저 클래스들이 각각의 고유한 게임 시스템(건물, 자원, 연구 등)을 독립적으로 관리하며,
Redis 캐시와 DB 매니저를 결합하여 데이터의 무결성과 성능을 동시에 확보합니다.

2. 핵심 매니저 기능 (Main Managers)

   - ResourceManager: 5대 주요 자원의 원자적 소모 및 생산 관리.
   - BuildingManager: 영지 내 건물의 건설 및 레벨업 프로세스 조율.
   - ResearchManager: 기술 트리 진행 및 연구 완료 시 영구 버프 활성화.
   - BuffManager: 영구/임시 버프의 실시간 합산 및 최종 스탯 계산.
   - HeroManager: 영웅 생성, 랜덤 스탯 부여 및 육성 데이터 관리.
   - MissionManager: 유저 액션에 따른 미션 달성 여부 검증 및 보상 처리.
   - ItemManager: 소비성 아이템의 사용 효과 적용 및 인벤토리 동기화.
   - AllianceManager: 연맹 시스템(가입, 기부, 소셜 버프) 전반 관리.
   - ShopManager: 가중치 기반 랜덤 아이템 리스트 생성 및 구매 처리.

3. 기술적 표준 (Technical Standards)

   - Redis-Aside Pattern: 읽기/쓰기 시 Redis 캐시를 최우선으로 활용합니다.
   - Inter-Manager Calling: 각 매니저는 필요한 경우 타 도메인 매니저를 호출하여 
     로직을 완결합니다 (예: 건물 건설 시 자원 매니저 호출).
   - Async Workflow: 전체 로직은 비동기(async/await)로 작성되어 동시성을 보장합니다.

4. 관리 지침 (Maintenance)
   - 새로운 도메인 추가 시 GameDataManager의 REQUIRE_CONFIGS와 연동 여부를 확인하십시오.
   - 자원 소모 로직은 반드시 ResourceManager의 원자적 연산을 거쳐야 합니다.

--------------------------------------------------
Last Updated: 2026-02-12
Created by: Gemini (AI Collaborator)
--------------------------------------------------
