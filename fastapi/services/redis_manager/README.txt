📂 /services/redis_manager/README.txt

==================================================
Redis Manager Service Layer - Overview
==================================================

1. 개요 (Overview)
본 폴더는 게임 서비스의 실시간성과 비동기 성능을 극대화하기 위한 'Redis 관리 레이어'입니다. 
aioredis(비동기 라이브러리)를 기반으로 설계되었으며, 게임 엔진의 다양한 도메인(건물, 유닛, 연구 등)에 
대한 캐싱 및 태스크 큐잉(Task Queuing) 작업을 전담합니다.

2. 주요 아키텍처 (Core Architecture)
이 시스템은 '중앙 집중형 접근'과 '도메인별 분리' 원칙을 따릅니다.

   - Facade Pattern: RedisManager.py가 모든 하위 매니저의 엔트리 포인트 역할을 수행합니다.
   - Singleton-like Access: RedisManager 인스턴스를 통해 각 도메인 매니저(Building, Unit 등)에 
     지연 로딩(Lazy Loading) 방식으로 접근합니다.
   - Component-based: 각 매니저는 내부적으로 TaskManager와 CacheManager 컴포넌트를 조합하여 
     로직을 처리합니다.

3. 주요 컴포넌트 상세 (Key Components)

   - RedisManager.py: 
     전체 서비스의 허브입니다. 건물, 유닛, 아이템, 미션 등 모든 도메인 매니저를 관리하며 
     HSET, ZADD, GET 등 공통적인 Redis 커맨드를 비동기로 래핑하여 제공합니다.

   - BuildingRedisManager.py: 
     건물 시스템 전용 로직을 담당합니다. 
     * Task Management: 건물의 업그레이드나 생산 완료 시간을 Sorted Set으로 관리합니다.
     * Caching: 유저별 건물 정보를 Hash 구조로 저장하여 고속 조회를 지원합니다.

   - redis_data_checker.py: 
     운영 및 디버깅용 유틸리티입니다. Redis 내부의 데이터 타입 확인, 키 존재 여부, 
     JSON 데이터의 역직렬화 및 메모리 크기 등을 모니터링하는 기능을 제공합니다.

4. 데이터 처리 로직 (Data Handling)

   - 비동기 처리 (Async/Await): 모든 IO 작업은 Non-blocking 방식으로 처리되어 서버 부하를 최소화합니다.
   - 우선순위 큐 (Sorted Sets): '완료 시간'을 Score로 사용하여, 현재 시간 기준으로 
     완료된 작업을 효율적으로 추출(get_completed_tasks)합니다.
   - 효율적 캐싱 (Hashes): 유저의 방대한 데이터를 필드 단위로 나누어 저장함으로써, 
     불필요한 전체 데이터 로드 없이 특정 필드만 업데이트할 수 있습니다.

5. 사용 가이드 (Usage)
   항상 RedisManager 인스턴스를 통해 각 도메인 매니저를 호출하십시오.
   예: manager.get_building_manager().add_building_to_queue(...)

--------------------------------------------------
Last Updated: 2026-02-12
Created by: Gemini (AI Collaborator)
--------------------------------------------------
