"""
Phase 2: 행군/전투 생성 부하 테스트

목표:
  - 다수 유저가 동시에 행군 생성 → NPC 전투 발생
  - TaskWorker 처리 지연 측정 (행군 도착 → 전투 시작 시간)
  - BattleWorker 동시 활성 전투 처리 성능
  - Redis 풀 소모율 (Worker + API 동시 사용)

시나리오:
  1. 유저 생성 + 유닛 훈련 (사전 준비)
  2. NPC 행군 반복 생성
  3. 행군 목록/전투 정보 조회 (전투 중 읽기 부하)

실행:
  locust -f phase2_march_battle.py --host http://localhost:8000
  locust -f phase2_march_battle.py --host http://localhost:8000 --headless -u 30 -r 5 -t 5m
"""

import random
import time
from locust import HttpUser, task, between, events, tag
from helpers import GameApiMixin, check_success
from config import ApiCode
import logging

logger = logging.getLogger(__name__)


class NpcHunter(GameApiMixin, HttpUser):
    """NPC 사냥을 반복하는 유저"""

    wait_time = between(1, 3)

    def on_start(self):
        """유저 생성 + 영웅 부여 + 유닛 확보"""
        self.setup_test_user()
        self.grant_hero(1001)

        # 유닛 정보 조회하여 ready 유닛 확인
        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] setup_unit_check")
        self.available_units = {}
        if check_success(resp):
            try:
                units = resp.json().get("data", {}).get("units", [])
                for u in units:
                    ready = int(u.get("ready", 0))
                    if ready > 0:
                        self.available_units[u["unit_idx"]] = ready
            except Exception:
                pass

        # ready 유닛이 부족하면 훈련 시도
        if not self.available_units:
            self.train_units(401, 50)
            self.train_units(402, 50)

        self.active_marches = 0
        self.max_marches = 3  # 서버 제한

    @task(5)
    @tag("march")
    def send_npc_march(self):
        """NPC 행군 생성 (최대 3개 행군 제한)"""
        if self.active_marches >= self.max_marches:
            return

        # 사용 가능한 유닛이 있으면 행군
        units_to_send = {}
        resp = self.api_call(ApiCode.UNIT_INFO, name="[4001] pre_march_check")
        if check_success(resp):
            try:
                unit_list = resp.json().get("data", {}).get("units", [])
                for u in unit_list:
                    ready = int(u.get("ready", 0))
                    if ready >= 10:
                        units_to_send[str(u["unit_idx"])] = min(ready, 20)
                    if len(units_to_send) >= 2:
                        break
            except Exception:
                pass

        if not units_to_send:
            return

        # 랜덤 NPC 선택 (npc_id 1~5)
        npc_id = random.randint(1, 5)
        npc_resp = self.api_call(ApiCode.NPC_LIST, name="[9003] npc_for_march")
        target_x, target_y = 15, 25  # 기본값

        if check_success(npc_resp):
            try:
                npcs = npc_resp.json().get("data", {}).get("npcs", [])
                alive_npcs = [n for n in npcs if n.get("alive")]
                if alive_npcs:
                    chosen = random.choice(alive_npcs)
                    npc_id = chosen.get("npc_id", npc_id)
                    target_x = chosen.get("x", target_x)
                    target_y = chosen.get("y", target_y)
            except Exception:
                pass

        resp = self.create_march(
            units=units_to_send,
            target_x=target_x,
            target_y=target_y,
            target_type="npc",
            npc_id=npc_id,
            hero_idx=1001,
        )
        if check_success(resp):
            self.active_marches += 1

    @task(3)
    @tag("query")
    def check_march_status(self):
        """행군 목록 조회 — 진행 중인 행군 상태 확인"""
        resp = self.api_call(ApiCode.MARCH_LIST, name="[9011] march_list")
        if check_success(resp):
            try:
                marches = resp.json().get("data", {}).get("marches", [])
                # 완료된 행군 수만큼 active_marches 감소
                active = len([m for m in marches if m.get("status") in ("marching", "battling")])
                self.active_marches = active
            except Exception:
                pass

    @task(2)
    @tag("query")
    def check_battle_report(self):
        """전투 기록 조회"""
        self.api_call(ApiCode.BATTLE_REPORT, name="[9022] battle_report")

    @task(2)
    @tag("query")
    def check_resources(self):
        """자원 조회 (전투 보상 확인용)"""
        self.api_call(ApiCode.RESOURCE_INFO, name="[1011] resource_info")


class UnitTrainer(GameApiMixin, HttpUser):
    """
    전투 중 유닛 훈련을 지속하는 유저 (Worker 부하 추가).
    TaskWorker가 유닛 완료 + 전투 도착을 동시에 처리해야 하는 상황 생성.
    """

    wait_time = between(2, 5)
    weight = 3  # NpcHunter 대비 30% 비율

    def on_start(self):
        self.setup_test_user()

    @task(3)
    def train_infantry(self):
        """보병 훈련"""
        self.train_units(401, random.randint(10, 30))

    @task(2)
    def train_heavy(self):
        """중보병 훈련"""
        self.train_units(402, random.randint(5, 20))

    @task(1)
    def check_unit_status(self):
        """유닛 상태 조회"""
        self.api_call(ApiCode.UNIT_INFO, name="[4001] unit_info")

    @task(1)
    def finish_training(self):
        """훈련 완료 처리"""
        self.api_call(ApiCode.UNIT_INFO, {"finish_check": True}, name="[4004] unit_finish")
