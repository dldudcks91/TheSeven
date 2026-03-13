"""
부하 테스트 공통 설정
- 서버 URL, 테스트 유저 범위, 타이밍 등 한곳에서 관리
"""

# ── 서버 설정 ──
BASE_URL = "http://localhost:8000"
API_ENDPOINT = "/api"
WS_ENDPOINT = "ws://localhost:8000/ws"
HEALTH_ENDPOINT = "/health"
POOL_STATUS_ENDPOINT = "/pool-status"

# ── 테스트 유저 설정 ──
# 부하 테스트 전용 유저 번호 범위 (운영 데이터와 겹치지 않게)
LOAD_TEST_USER_START = 90001
LOAD_TEST_USER_END = 91000

# ── API 코드 ──
class ApiCode:
    # 시스템
    LOGIN = 1010
    CREATE_USER = 1003
    GAME_DATA = 1002
    RESOURCE_INFO = 1011
    BUFF_INFO = 1012

    # 건물
    BUILDING_INFO = 2001
    BUILDING_CREATE = 2002

    # 유닛
    UNIT_INFO = 4001
    UNIT_TRAIN = 4002

    # 영웅
    HERO_LIST = 8001
    HERO_GRANT = 8002

    # 맵/행군
    MY_POSITION = 9001
    MAP_INFO = 9002
    NPC_LIST = 9003
    MARCH_LIST = 9011
    MARCH_CREATE = 9012
    MARCH_CANCEL = 9013

    # 전투
    BATTLE_INFO = 9021
    BATTLE_REPORT = 9022

    # 집결
    RALLY_CREATE = 9031
    RALLY_JOIN = 9032
    RALLY_INFO = 9033

    # 전장
    BATTLEFIELD_LIST = 9050
    BATTLEFIELD_JOIN = 9051
    BATTLEFIELD_RETREAT = 9052
    BATTLEFIELD_INFO = 9053
    BATTLEFIELD_WATCH = 9054
    BATTLEFIELD_UNWATCH = 9055


# ── 부하 테스트 프로파일 ──
PROFILES = {
    "smoke": {
        "users": 5,
        "spawn_rate": 1,
        "run_time": "30s",
        "description": "기본 동작 확인 (5명, 30초)",
    },
    "light": {
        "users": 20,
        "spawn_rate": 5,
        "run_time": "2m",
        "description": "경량 부하 (20명, 2분)",
    },
    "medium": {
        "users": 50,
        "spawn_rate": 10,
        "run_time": "5m",
        "description": "중간 부하 — Redis 풀 50 한계 근접 (50명, 5분)",
    },
    "heavy": {
        "users": 100,
        "spawn_rate": 20,
        "run_time": "10m",
        "description": "고부하 — Redis 풀 초과 예상 (100명, 10분)",
    },
    "stress": {
        "users": 200,
        "spawn_rate": 50,
        "run_time": "15m",
        "description": "스트레스 — 서버 한계 탐색 (200명, 15분)",
    },
}
