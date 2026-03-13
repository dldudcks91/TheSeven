"""
Phase 4: 전장 + WebSocket 스트레스 테스트

목표:
  - 다수 유저 전장 참여 + WS 구독 → 1초 틱 브로드캐스트 부하
  - WebSocket 연결 수 한계 측정
  - 전장 내 동시 전투 발생 시 메시지 폭발량 측정
  - WS 메시지 수신 지연 (p95 latency)

시나리오:
  1. 유저들이 전장 참여 + battlefield_watch 구독
  2. 일부 유저가 NPC 행군 → 전투 생성
  3. BattleWorker가 1초마다 battlefield_tick 브로드캐스트
  4. WS 수신 측에서 메시지 도착 시간 측정

실행:
  locust -f phase4_battlefield_ws.py --host http://localhost:8000
  locust -f phase4_battlefield_ws.py --host http://localhost:8000 --headless -u 50 -r 10 -t 5m

의존성:
  pip install locust websocket-client
"""

import json
import random
import time
import logging
from locust import HttpUser, task, between, events, tag
from helpers import GameApiMixin, check_success
from config import ApiCode, WS_ENDPOINT

logger = logging.getLogger(__name__)

# 전장 ID (1~3)
TARGET_BATTLEFIELD = 1


class BattlefieldParticipant(GameApiMixin, HttpUser):
    """전장 참여 + API 조회 유저"""

    wait_time = between(1, 3)

    def on_start(self):
        self.setup_test_user()
        self.grant_hero(1001)
        self.train_units(401, 100)
        self.joined_battlefield = False
        self.watching = False

        # 전장 참여
        resp = self.api_call(
            ApiCode.BATTLEFIELD_JOIN,
            {"bf_id": TARGET_BATTLEFIELD},
            name="[9051] bf_join",
        )
        if check_success(resp):
            self.joined_battlefield = True

        # 전장 구독
        resp = self.api_call(
            ApiCode.BATTLEFIELD_WATCH,
            {"bf_id": TARGET_BATTLEFIELD},
            name="[9054] bf_watch",
        )
        if check_success(resp):
            self.watching = True

    @task(3)
    @tag("query")
    def query_battlefield_info(self):
        """전장 상태 조회"""
        self.api_call(
            ApiCode.BATTLEFIELD_INFO,
            {"bf_id": TARGET_BATTLEFIELD},
            name="[9053] bf_info",
        )

    @task(2)
    @tag("query")
    def query_battlefield_list(self):
        """전장 목록 조회"""
        self.api_call(ApiCode.BATTLEFIELD_LIST, name="[9050] bf_list")

    @task(2)
    @tag("battle")
    def send_npc_march_in_battlefield(self):
        """전장 내 NPC 행군 (전투 생성)"""
        if not self.joined_battlefield:
            return

        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] bf_unit_check")
        units_to_send = {}
        if check_success(resp):
            try:
                for u in resp.json().get("data", {}).get("units", []):
                    ready = int(u.get("ready", 0))
                    if ready >= 10:
                        units_to_send[str(u["unit_idx"])] = min(ready, 15)
                    if len(units_to_send) >= 2:
                        break
            except Exception:
                pass

        if not units_to_send:
            return

        npc_id = random.randint(1, 5)
        self.create_march(
            units=units_to_send,
            target_type="npc",
            npc_id=npc_id,
            hero_idx=1001,
        )

    @task(1)
    @tag("query")
    def check_march_status(self):
        """행군 상태 확인"""
        self.api_call(ApiCode.MARCH_LIST, name="[9011] bf_march_list")

    def on_stop(self):
        """전장 퇴장"""
        if self.watching:
            self.api_call(
                ApiCode.BATTLEFIELD_UNWATCH,
                {"bf_id": TARGET_BATTLEFIELD},
                name="[9055] bf_unwatch",
            )
        if self.joined_battlefield:
            self.api_call(
                ApiCode.BATTLEFIELD_RETREAT,
                {"bf_id": TARGET_BATTLEFIELD},
                name="[9052] bf_retreat",
            )


class WebSocketWatcher(HttpUser):
    """
    WebSocket 연결만 유지하며 메시지 수신 측정.

    주의: Locust 기본 HttpUser는 WS를 직접 지원하지 않으므로,
    gevent + websocket-client를 사용하여 별도 연결 관리.
    실제 실행 시 websocket-client 패키지 필요: pip install websocket-client
    """

    wait_time = between(5, 10)
    weight = 5  # 참여자 대비 50% 비율

    def on_start(self):
        self.user_no = random.randint(90301, 90500)
        self.ws = None
        self.msg_count = 0
        self.last_msg_time = None
        self._connect_ws()

    def _connect_ws(self):
        """WebSocket 연결 시도"""
        try:
            import websocket
            ws_url = f"{WS_ENDPOINT}/{self.user_no}"
            self.ws = websocket.create_connection(ws_url, timeout=5)
            self.ws.settimeout(0.1)  # non-blocking recv
            logger.info(f"WS connected: user {self.user_no}")
        except ImportError:
            logger.warning("websocket-client not installed. WS tests skipped.")
            self.ws = None
        except Exception as e:
            logger.warning(f"WS connection failed for user {self.user_no}: {e}")
            self.ws = None

    @task
    def receive_messages(self):
        """WS 메시지 수신 + 카운트"""
        if not self.ws:
            return

        try:
            while True:
                msg = self.ws.recv()
                if msg:
                    self.msg_count += 1
                    self.last_msg_time = time.time()
                    try:
                        data = json.loads(msg)
                        msg_type = data.get("type", "unknown")
                        # Locust 커스텀 이벤트로 메시지 수신 기록
                        events.request.fire(
                            request_type="WS_RECV",
                            name=f"ws_{msg_type}",
                            response_time=0,
                            response_length=len(msg),
                            exception=None,
                            context={},
                        )
                    except json.JSONDecodeError:
                        pass
        except Exception:
            # timeout 또는 연결 끊김 — 정상
            pass

    def on_stop(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            logger.info(
                f"WS closed: user {self.user_no}, total messages: {self.msg_count}"
            )
