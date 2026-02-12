📂 /services/system/README.txt

==================================================
System & Infrastructure Layer - Overview
==================================================

1. 개요 (Overview)
본 폴더는 서비스의 '관문(Gateway)'이자 '기반(Foundation)' 레이어입니다.
유저의 생성부터 로그인, API 라우팅, 소켓 통신 및 정적 데이터 관리를 포함한
시스템 전반의 핵심 인프라 로직을 담당합니다.

2. 주요 역할 (Core Roles)

   - API Gateway: APIManager.py가 클라이언트의 API 요청을 분석하여 
     적절한 도메인 서비스(Game, Resource 등)로 연결합니다.
   - User Lifecycle: UserInitManager(생성)와 LoginManager(데이터 로드)를 통해 
     유저의 진입과 데이터 동기화를 관리합니다.
   - Meta-Data Management: GameDataManager.py가 서버 기획 데이터를 
     CSV에서 메모리로 로드하여 전역에서 참조 가능하게 합니다.
   - Real-time Communication: WebsocketManager.py를 통해 클라이언트와의 
     실시간 세션을 유지하고 메시지를 전송합니다.

3. 주요 컴포넌트 (Key Components)

   - APIManager.py: API 코드 기반의 요청 분산기 (1xxx: System, 2xxx: Building 등).
   - LoginManager.py: 로그인 시 8개 이상의 도메인 데이터를 병렬로 로드하는 오케스트레이터.
   - UserInitManager.py: 원자적 ID 생성 및 초기 유저 환경(자원/건물) 구축.
   - GameDataManager.py: CSV 기반 게임 밸런스 데이터 로더 및 미션 인덱서.
   - WebsocketManager.py: 비동기 웹소켓 연결 관리 및 브로드캐스팅 유틸리티.

4. 기술적 특징 (Technical Highlights)

   - 비동기 처리: 전 과정에서 async/await를 사용하여 높은 동시성 처리를 보장합니다.
   - 병렬 로딩: asyncio.gather를 사용하여 로그인 및 데이터 초기화 성능을 최적화했습니다.
   - 무결성 보장: DB 트랜잭션과 Counter 시스템을 통해 유저 생성 시 데이터 결함을 방지합니다.

5. 관리 지침 (Maintenance)
   - 새로운 API 개발 시 APIManager.api_map에 반드시 등록하십시오.
   - 메타데이터(CSV) 변경 시 서버 재시작 또는 GameDataManager 재로딩이 필요합니다.

--------------------------------------------------
Last Updated: 2026-02-12
Created by: Gemini (AI Collaborator)
--------------------------------------------------
