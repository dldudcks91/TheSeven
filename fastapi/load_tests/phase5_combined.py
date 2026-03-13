"""
Phase 5: 복합 시나리오 (전체 동시 실행)

목표:
  - 실제 운영 환경과 유사한 혼합 부하 생성
  - Redis 커넥션 풀 고갈 시점 파악
  - 서버 안정성 한계 탐색 (크래시/타임아웃 발생 지점)
  - Worker 처리 지연이 API 응답에 미치는 영향

시나리오 혼합 비율:
  - 조회 유저 (50%): 자원/유닛/건물 조회만
  - NPC 사냥 유저 (25%): 행군 + 전투
  - 성 공격 유저 (15%): PvP 행군
  - 전장 유저 (10%): 전장 참여 + WS 구독

실행:
  locust -f phase5_combined.py --host http://localhost:8000
  locust -f phase5_combined.py --host http://localhost:8000 --headless -u 100 -r 20 -t 10m
"""

import random
import time
import logging
from locust import HttpUser, task, between, events
from helpers import GameApiMixin, check_success
from config import ApiCode, POOL_STATUS_ENDPOINT

logger = logging.getLogger(__name__)


class CasualPlayer(GameApiMixin, HttpUser):
    """
    조회 중심 유저 (50%) — 자원/유닛/건물/영웅 조회.
    가장 흔한 유저 패턴.
    """

    wait_time = between(1, 3)
    weight = 50

    def on_start(self):
        self.setup_test_user()

    @task(5)
    def query_resources(self):
        self.api_call(ApiCode.RESOURCE_INFO, name="[1011] resource_info")

    @task(3)
    def query_units(self):
        self.api_call(ApiCode.UNIT_INFO, name="[4001] unit_info")

    @task(3)
    def query_buildings(self):
        self.api_call(ApiCode.BUILDING_INFO, name="[2001] building_info")

    @task(2)
    def query_heroes(self):
        self.api_call(ApiCode.HERO_LIST, name="[8001] hero_list")

    @task(1)
    def query_map(self):
        self.api_call(
            ApiCode.MAP_INFO,
            {"center_x": 50, "center_y": 50, "range": 10},
            name="[9002] map_info",
        )


class ActiveHunter(GameApiMixin, HttpUser):
    """
    NPC 사냥 유저 (25%) — 행군 + 전투 + 조회 혼합.
    """

    wait_time = between(1, 4)
    weight = 25

    def on_start(self):
        self.setup_test_user()
        self.grant_hero(1001)
        self.train_units(401, 100)
        self.active_marches = 0

    @task(4)
    def hunt_npc(self):
        if self.active_marches >= 3:
            return

        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] hunter_unit_check")
        units = {}
        if check_success(resp):
            try:
                for u in resp.json().get("data", {}).get("units", []):
                    ready = int(u.get("ready", 0))
                    if ready >= 10:
                        units[str(u["unit_idx"])] = min(ready, 20)
                    if len(units) >= 2:
                        break
            except Exception:
                pass

        if not units:
            # 유닛 부족 → 훈련
            self.train_units(401, 30)
            return

        npc_id = random.randint(1, 5)
        resp = self.create_march(
            units=units, target_type="npc", npc_id=npc_id, hero_idx=1001,
        )
        if check_success(resp):
            self.active_marches += 1

    @task(3)
    def check_marches(self):
        resp = self.api_call(ApiCode.MARCH_LIST, name="[9011] hunter_march_list")
        if check_success(resp):
            try:
                marches = resp.json().get("data", {}).get("marches", [])
                self.active_marches = len(
                    [m for m in marches if m.get("status") in ("marching", "battling")]
                )
            except Exception:
                pass

    @task(2)
    def check_resources(self):
        self.api_call(ApiCode.RESOURCE_INFO, name="[1011] hunter_resources")

    @task(1)
    def check_battle_report(self):
        self.api_call(ApiCode.BATTLE_REPORT, name="[9022] hunter_report")


class PvPAttacker(GameApiMixin, HttpUser):
    """
    PvP 공격 유저 (15%) — 랜덤 유저 성 공격.
    """

    wait_time = between(2, 5)
    weight = 15

    # 공격 대상 풀 (사전 준비된 유저)
    TARGET_POOL = list(range(90001, 90010))

    def on_start(self):
        self.user_no = random.randint(90501, 90700)
        self.api_call(ApiCode.CREATE_USER, name="[1003] pvp_create")
        self.api_call(ApiCode.LOGIN, name="[1010] pvp_login")
        self.grant_hero(1001)
        self.train_units(401, 100)
        self.train_units(402, 50)
        self.has_marched = False

    @task(3)
    def attack_random_player(self):
        if self.has_marched:
            return

        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] pvp_unit_check")
        units = {}
        if check_success(resp):
            try:
                for u in resp.json().get("data", {}).get("units", []):
                    ready = int(u.get("ready", 0))
                    if ready >= 10:
                        units[str(u["unit_idx"])] = min(ready, 25)
            except Exception:
                pass

        if not units:
            return

        target = random.choice(self.TARGET_POOL)
        data = {
            "units": units,
            "target_x": 50,
            "target_y": 50,
            "target_type": "user",
            "target_user_no": target,
            "hero_idx": 1001,
        }
        resp = self.api_call(ApiCode.MARCH_CREATE, data, name="[9012] pvp_attack")
        if check_success(resp):
            self.has_marched = True

    @task(3)
    def check_status(self):
        resp = self.api_call(ApiCode.MARCH_LIST, name="[9011] pvp_march_list")
        if check_success(resp) and self.has_marched:
            try:
                marches = resp.json().get("data", {}).get("marches", [])
                active = [m for m in marches if m.get("status") in ("marching", "battling")]
                if not active:
                    self.has_marched = False
            except Exception:
                pass

    @task(2)
    def check_resources(self):
        self.api_call(ApiCode.RESOURCE_INFO, name="[1011] pvp_resources")


class BattlefieldUser(GameApiMixin, HttpUser):
    """
    전장 유저 (10%) — 전장 참여 + 조회.
    """

    wait_time = between(2, 5)
    weight = 10

    def on_start(self):
        self.setup_test_user()
        self.grant_hero(1001)
        self.train_units(401, 50)

        bf_id = random.randint(1, 3)
        self.bf_id = bf_id
        self.api_call(
            ApiCode.BATTLEFIELD_JOIN,
            {"bf_id": bf_id},
            name="[9051] combined_bf_join",
        )
        self.api_call(
            ApiCode.BATTLEFIELD_WATCH,
            {"bf_id": bf_id},
            name="[9054] combined_bf_watch",
        )

    @task(3)
    def query_battlefield(self):
        self.api_call(
            ApiCode.BATTLEFIELD_INFO,
            {"bf_id": self.bf_id},
            name="[9053] combined_bf_info",
        )

    @task(2)
    def hunt_in_battlefield(self):
        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] bf_unit_check")
        units = {}
        if check_success(resp):
            try:
                for u in resp.json().get("data", {}).get("units", []):
                    ready = int(u.get("ready", 0))
                    if ready >= 5:
                        units[str(u["unit_idx"])] = min(ready, 10)
                    if units:
                        break
            except Exception:
                pass
        if units:
            self.create_march(
                units=units, target_type="npc",
                npc_id=random.randint(1, 3), hero_idx=1001,
            )

    @task(1)
    def check_marches(self):
        self.api_call(ApiCode.MARCH_LIST, name="[9011] bf_march_list")

    def on_stop(self):
        self.api_call(
            ApiCode.BATTLEFIELD_UNWATCH,
            {"bf_id": self.bf_id},
            name="[9055] combined_bf_unwatch",
        )
        self.api_call(
            ApiCode.BATTLEFIELD_RETREAT,
            {"bf_id": self.bf_id},
            name="[9052] combined_bf_retreat",
        )


# ── Redis 풀 모니터링 (Phase 1과 동일) ──
pool_monitor_running = False


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global pool_monitor_running
    pool_monitor_running = True
    import gevent
    gevent.spawn(_monitor_pool, environment)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    global pool_monitor_running
    pool_monitor_running = False


def _monitor_pool(environment):
    import gevent
    import requests

    host = environment.host or "http://localhost:8000"
    while pool_monitor_running:
        try:
            resp = requests.get(f"{host}/pool-status", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                rp = data.get("redis_pool", {})
                dp = data.get("db_pool", {})
                logger.info(
                    f"[POOL] Redis in_use={rp.get('in_use_connections','?')}/"
                    f"{rp.get('max_connections','?')} | "
                    f"DB checked_out={dp.get('checked_out','?')}"
                )
        except Exception as e:
            logger.warning(f"[POOL] monitor error: {e}")
        gevent.sleep(5)  # 5초 간격 (부하 높으므로 더 자주)
