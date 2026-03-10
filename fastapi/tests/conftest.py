"""
TheSeven 테스트 인프라
- DB: theseven_test (MySQL, 테스트 간 테이블 truncate)
- Redis: fakeredis (인메모리, 테스트 간 flushall)
- GameDataManager: CSV 1회 로드 (세션 스코프)
- Background Workers: 미실행 (테스트에서 불필요)
"""
import os
import sys
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import fakeredis.aioredis

# fastapi/ 디렉토리를 sys.path에 추가 (import 경로 해결)
# 주의: 프로젝트 디렉토리명이 'fastapi'이므로 부모 디렉토리가 sys.path에 있으면
#       실제 FastAPI 라이브러리를 가린다. 부모 디렉토리는 반드시 제거.
FASTAPI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_OF_FASTAPI = os.path.dirname(FASTAPI_DIR)

# 부모 디렉토리 제거 (fastapi 패키지 shadowing 방지)
sys.path = [p for p in sys.path if os.path.normcase(os.path.abspath(p)) != os.path.normcase(PARENT_OF_FASTAPI)]

if FASTAPI_DIR not in sys.path:
    sys.path.insert(0, FASTAPI_DIR)


# ---------------------------------------------------------------------------
# 1. Test DB (MySQL theseven_test)
# ---------------------------------------------------------------------------
TEST_DB_URL = "mysql+pymysql://root:an98@localhost:3306/theseven_test?charset=utf8mb4"

test_engine = create_engine(TEST_DB_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """세션 시작 시 테스트 DB에 테이블 생성"""
    import models
    models.Base.metadata.create_all(bind=test_engine)
    yield
    # 세션 종료 후 테이블 유지 (필요 시 drop_all 활성화)


@pytest.fixture(autouse=True)
def clean_db():
    """각 테스트 시작 전 모든 테이블 데이터 삭제"""
    with test_engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in _get_table_names():
            conn.execute(text(f"DELETE FROM `{table}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()
    yield


def _get_table_names():
    """SQLAlchemy 2.x 호환 테이블 이름 조회"""
    from sqlalchemy import inspect
    inspector = inspect(test_engine)
    return inspector.get_table_names()


# ---------------------------------------------------------------------------
# 2. Test Redis (fakeredis)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def fake_redis():
    """테스트용 fakeredis 인스턴스 + Lua 미지원 패치"""
    server = fakeredis.aioredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    # fakeredis가 EVAL(Lua)을 지원하지 않으므로 atomic_consume을 non-Lua로 패치
    from services.redis_manager.resource_redis_manager import ResourceRedisManager
    _original_atomic_consume = ResourceRedisManager.atomic_consume

    async def _patched_atomic_consume(self, user_no, costs):
        """테스트용 non-Lua atomic_consume (단일 스레드이므로 원자성 불필요)"""
        if not costs:
            return {"success": True, "remaining": {}}
        try:
            hash_key = self.cache_manager.get_user_data_hash_key(user_no)
            # 1단계: 잔액 확인
            for res_type, cost in costs.items():
                if cost <= 0:
                    continue
                current = await self.redis_client.hget(hash_key, res_type)
                current_val = int(current) if current is not None else 0
                if current_val < cost:
                    return {
                        "success": False,
                        "reason": "insufficient",
                        "shortage": {res_type: {"required": cost, "current": current_val}}
                    }
            # 2단계: 차감
            remaining = {}
            for res_type, cost in costs.items():
                if cost <= 0:
                    continue
                new_val = await self.redis_client.hincrby(hash_key, res_type, -cost)
                remaining[res_type] = new_val
            return {"success": True, "remaining": remaining}
        except Exception as e:
            return {"success": False, "reason": "error", "message": str(e)}

    ResourceRedisManager.atomic_consume = _patched_atomic_consume

    yield client

    # 원본 복구
    ResourceRedisManager.atomic_consume = _original_atomic_consume
    await client.aclose()


# ---------------------------------------------------------------------------
# 3. GameDataManager 초기화 (세션 1회)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def load_game_data():
    """CSV 메타데이터 로드 - 세션 전체에서 1회"""
    original_dir = os.getcwd()
    os.chdir(FASTAPI_DIR)
    try:
        from services.system import GameDataManager
        GameDataManager.initialize()
    finally:
        os.chdir(original_dir)


# ---------------------------------------------------------------------------
# 4. FastAPI 의존성 오버라이드 + AsyncClient
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(fake_redis):
    """
    테스트용 AsyncClient.
    - DB: theseven_test 세션
    - Redis: fakeredis
    - WebSocket: None (테스트에서 미사용)
    - Background Workers: 미실행
    """
    from main import app
    from services.db_manager import DBManager
    from services.redis_manager import RedisManager
    from services.system import WebsocketManager

    # startup/shutdown 이벤트 비활성화 (실제 Redis 연결, Worker 시작 방지)
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    # 테스트용 의존성 생성 함수
    def override_get_db_manager():
        db_session = TestSessionLocal()
        try:
            return DBManager(db_session)
        except Exception:
            db_session.close()
            raise

    async def override_get_redis_manager():
        return RedisManager(fake_redis)

    def override_get_websocket_manager():
        return WebsocketManager()

    # FastAPI 의존성 오버라이드
    from main import get_db_manager, get_redis_manager, get_websocket_manager
    app.dependency_overrides[get_db_manager] = override_get_db_manager
    app.dependency_overrides[get_redis_manager] = override_get_redis_manager
    app.dependency_overrides[get_websocket_manager] = override_get_websocket_manager

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # 오버라이드 정리
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. 헬퍼: 테스트용 유저 생성
# ---------------------------------------------------------------------------
@pytest.fixture
def test_user_no():
    """테스트용 유저 번호"""
    return 99999


@pytest.fixture
def create_test_user(test_user_no):
    """테스트 DB에 기본 유저 데이터 삽입"""
    session = TestSessionLocal()
    try:
        from models import StatNation, Resources
        import datetime

        nation = StatNation(
            account_no=99999,
            user_no=test_user_no,
            alliance_no=0,
            name="TestUser",
            hq_lv=1,
            power=0,
            cr_dt=datetime.datetime.now(),
            last_dt=datetime.datetime.now(),
        )
        session.add(nation)

        resources = Resources(
            user_no=test_user_no,
            food=100000,
            wood=100000,
            stone=100000,
            gold=100000,
            ruby=1000,
        )
        session.add(resources)
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 6. 헬퍼: API 호출 단축 함수
# ---------------------------------------------------------------------------
@pytest.fixture
def api_call(client):
    """API 호출 헬퍼: api_call(user_no, api_code, data) -> response json"""
    async def _call(user_no: int, api_code: int, data: dict = None):
        resp = await client.post("/api", json={
            "user_no": user_no,
            "api_code": api_code,
            "data": data or {}
        })
        return resp.json()
    return _call
