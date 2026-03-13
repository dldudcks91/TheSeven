"""
Phase 3: 동시 성 공격 테스트

목표:
  - N명이 동일 유저의 성을 동시에 공격
  - process_castle_tick 그룹 스냅샷 처리 정합성
  - 멀티 어태커 자원 약탈 분배 정확성
  - 방어자 유닛 상태 동시성 문제

시나리오:
  1. 방어자 1명: 유닛 대량 보유
  2. 공격자 N명: 동시에 같은 성으로 행군
  3. 전투 중 방어자가 유닛 훈련 시도 (타이밍 경합)

실행:
  locust -f phase3_castle_siege.py --host http://localhost:8000
  locust -f phase3_castle_siege.py --host http://localhost:8000 --headless -u 15 -r 5 -t 5m

주의:
  이 테스트는 방어자(DEFENDER_USER_NO)가 사전에 존재해야 합니다.
  먼저 서버에 해당 유저 + 유닛을 준비하세요.
"""

import random
import time
from locust import HttpUser, task, between, events, tag
from helpers import GameApiMixin, check_success
from config import ApiCode, LOAD_TEST_USER_START
import logging

logger = logging.getLogger(__name__)

# ── 방어자 설정 (사전 준비 필요) ──
DEFENDER_USER_NO = 90001  # 공격 대상 유저
ATTACKER_START = 90101    # 공격자 유저 범위 시작
ATTACKER_END = 90200      # 공격자 유저 범위 끝


class DefenderSetup(GameApiMixin, HttpUser):
    """
    방어자 1명 — 유닛 대량 보유 + 전투 중 훈련 시도.
    fixed_count=1 로 실행하거나, weight를 아주 낮게 설정.
    """

    wait_time = between(2, 5)
    weight = 1  # 공격자 대비 극소수
    fixed_count = 1

    def on_start(self):
        self.user_no = DEFENDER_USER_NO
        # 유저 생성 + 로그인
        self.api_call(ApiCode.CREATE_USER, name="[1003] defender_create")
        self.api_call(ApiCode.LOGIN, name="[1010] defender_login")
        # 대량 유닛 훈련
        for unit_idx in [401, 402, 403]:
            self.train_units(unit_idx, 200)
        logger.info(f"Defender {self.user_no} setup complete")

    @task(3)
    def query_own_status(self):
        """방어자: 자기 상태 조회 (전투 중)"""
        self.api_call(ApiCode.UNIT_INFO, name="[4001] defender_unit_info")

    @task(2)
    def query_resources(self):
        """방어자: 자원 변화 모니터링"""
        self.api_call(ApiCode.RESOURCE_INFO, name="[1011] defender_resources")

    @task(1)
    def train_during_battle(self):
        """방어자: 전투 중 유닛 훈련 시도 (타이밍 경합 유발)"""
        self.train_units(401, 50)


class CastleAttacker(GameApiMixin, HttpUser):
    """
    공격자 — 방어자 성으로 행군 + 전투 상태 확인.
    다수의 공격자가 동시에 같은 성을 공격.
    """

    wait_time = between(1, 3)
    weight = 10  # 공격자가 훨씬 많음

    def on_start(self):
        self.user_no = random.randint(ATTACKER_START, ATTACKER_END)
        self.api_call(ApiCode.CREATE_USER, name="[1003] attacker_create")
        self.api_call(ApiCode.LOGIN, name="[1010] attacker_login")
        self.grant_hero(1001)
        # 공격용 유닛 훈련
        self.train_units(401, 100)
        self.train_units(402, 50)
        self.has_marched = False
        self.attack_sent_at = None

    @task(5)
    @tag("attack")
    def attack_castle(self):
        """방어자 성 공격 행군"""
        if self.has_marched:
            return

        # 유닛 확인
        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] pre_attack_check")
        units_to_send = {}
        if check_success(resp):
            try:
                unit_list = resp.json().get("data", {}).get("units", [])
                for u in unit_list:
                    ready = int(u.get("ready", 0))
                    if ready >= 10:
                        units_to_send[str(u["unit_idx"])] = min(ready, 30)
            except Exception:
                pass

        if not units_to_send:
            return

        # 방어자 위치 조회
        target_x, target_y = 50, 50  # 기본값
        resp = self.api_call(
            ApiCode.MAP_INFO,
            {"center_x": 50, "center_y": 50, "range": 50},
            name="[9002] find_defender",
        )

        # 행군 생성 (유저 공격)
        data = {
            "units": units_to_send,
            "target_x": target_x,
            "target_y": target_y,
            "target_type": "user",
            "target_user_no": DEFENDER_USER_NO,
        }
        if 1001 in [1001]:  # hero
            data["hero_idx"] = 1001

        march_resp = self.api_call(
            ApiCode.MARCH_CREATE,
            data,
            name="[9012] march_attack_castle",
        )
        if check_success(march_resp):
            self.has_marched = True
            self.attack_sent_at = time.time()
            logger.info(f"Attacker {self.user_no} sent march to defender {DEFENDER_USER_NO}")

    @task(3)
    @tag("query")
    def check_battle_status(self):
        """전투 진행 상태 확인"""
        if not self.has_marched:
            return
        self.api_call(ApiCode.MARCH_LIST, name="[9011] attacker_march_list")

    @task(2)
    @tag("query")
    def check_battle_report(self):
        """전투 종료 후 결과 조회"""
        self.api_call(ApiCode.BATTLE_REPORT, name="[9022] attacker_battle_report")

    @task(1)
    @tag("query")
    def check_resources_after_battle(self):
        """전투 후 자원 변화 확인 (약탈 결과)"""
        self.api_call(ApiCode.RESOURCE_INFO, name="[1011] attacker_resources")

    @task(1)
    @tag("recovery")
    def retry_after_return(self):
        """행군 귀환 후 재공격 시도"""
        if not self.has_marched:
            return
        # 행군이 끝났는지 확인
        resp = self.api_call(ApiCode.MARCH_LIST, name="[9011] check_return")
        if check_success(resp):
            try:
                marches = resp.json().get("data", {}).get("marches", [])
                active = [m for m in marches if m.get("status") in ("marching", "battling")]
                if not active and self.has_marched:
                    # 행군 완료 → 재공격 가능
                    self.has_marched = False
                    logger.info(f"Attacker {self.user_no} ready for re-attack")
            except Exception:
                pass
