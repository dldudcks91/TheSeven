"""
Phase 1: API 기본 처리량 테스트

목표:
  - 서버 기본 throughput 측정 (RPS)
  - 응답 시간 p50 / p95 / p99
  - Redis 커넥션 풀 사용률 모니터링

시나리오:
  각 유저가 로그인 후 자원/유닛/건물/영웅 조회를 반복 수행.
  쓰기 없는 읽기 전용 부하 → 순수 API 처리 성능 측정.

실행:
  locust -f phase1_api_throughput.py --host http://localhost:8000
  locust -f phase1_api_throughput.py --host http://localhost:8000 --headless -u 50 -r 10 -t 5m
"""

from locust import HttpUser, task, between, events
from helpers import GameApiMixin, check_success
from config import ApiCode, HEALTH_ENDPOINT, POOL_STATUS_ENDPOINT
import logging
import time

logger = logging.getLogger(__name__)


class ReadOnlyUser(GameApiMixin, HttpUser):
    """읽기 전용 유저 — 조회 API만 반복 호출"""

    wait_time = between(0.5, 2)  # 요청 간 0.5~2초 대기

    def on_start(self):
        self.setup_test_user()

    @task(5)
    def query_resources(self):
        """자원 조회 (가장 빈번한 API)"""
        resp = self.api_call(ApiCode.RESOURCE_INFO, name="[1011] resource_info")
        if not check_success(resp):
            resp.failure(f"resource_info failed: {resp.text[:200]}")

    @task(3)
    def query_units(self):
        """유닛 조회"""
        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] unit_info")
        if not check_success(resp):
            resp.failure(f"unit_info failed: {resp.text[:200]}")

    @task(3)
    def query_buildings(self):
        """건물 조회"""
        resp = self.api_call(ApiCode.BUILDING_INFO, name="[2001] building_info")
        if not check_success(resp):
            resp.failure(f"building_info failed: {resp.text[:200]}")

    @task(2)
    def query_heroes(self):
        """영웅 목록 조회"""
        resp = self.api_call(ApiCode.HERO_LIST, name="[8001] hero_list")

    @task(2)
    def query_march_list(self):
        """행군 목록 조회"""
        resp = self.api_call(ApiCode.MARCH_LIST, name="[9011] march_list")

    @task(1)
    def query_map_info(self):
        """맵 정보 조회"""
        resp = self.api_call(
            ApiCode.MAP_INFO,
            {"center_x": 50, "center_y": 50, "range": 10},
            name="[9002] map_info",
        )

    @task(1)
    def query_npc_list(self):
        """NPC 목록 조회"""
        resp = self.api_call(ApiCode.NPC_LIST, name="[9003] npc_list")

    @task(1)
    def query_buffs(self):
        """버프 조회"""
        resp = self.api_call(ApiCode.BUFF_INFO, name="[1012] buff_info")


# ── 커넥션 풀 모니터링 (10초 간격) ──
pool_monitor_running = False


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """테스트 시작 시 풀 모니터링 시작"""
    global pool_monitor_running
    pool_monitor_running = True
    import gevent
    gevent.spawn(_monitor_pool, environment)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    global pool_monitor_running
    pool_monitor_running = False


def _monitor_pool(environment):
    """10초마다 /pool-status 호출하여 Redis 풀 상태 로깅"""
    import gevent
    import requests

    host = environment.host or "http://localhost:8000"
    while pool_monitor_running:
        try:
            resp = requests.get(f"{host}{POOL_STATUS_ENDPOINT}", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                redis_pool = data.get("redis_pool", {})
                logger.info(
                    f"[POOL] Redis — "
                    f"in_use: {redis_pool.get('in_use_connections', '?')}, "
                    f"available: {redis_pool.get('available_connections', '?')}, "
                    f"max: {redis_pool.get('max_connections', '?')}"
                )
        except Exception as e:
            logger.warning(f"[POOL] monitor error: {e}")
        gevent.sleep(10)
