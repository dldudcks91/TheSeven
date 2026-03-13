"""
부하 테스트 공통 헬퍼
- API 호출 래퍼, 유저 셋업, 결과 검증 등
"""
import json
import random
from config import (
    API_ENDPOINT, LOAD_TEST_USER_START, LOAD_TEST_USER_END, ApiCode
)


def api_payload(user_no: int, api_code: int, data: dict = None) -> dict:
    """POST /api 요청 바디 생성"""
    return {
        "user_no": user_no,
        "api_code": api_code,
        "data": data or {},
    }


def random_user_no() -> int:
    """테스트 유저 번호 랜덤 생성"""
    return random.randint(LOAD_TEST_USER_START, LOAD_TEST_USER_END)


def check_success(response) -> bool:
    """응답이 success: true인지 확인"""
    if response.status_code != 200:
        return False
    try:
        body = response.json()
        return body.get("success", False)
    except (json.JSONDecodeError, AttributeError):
        return False


class GameApiMixin:
    """
    Locust User 클래스에 믹스인으로 사용.
    self.client (Locust HttpSession) 가 있다고 가정.
    """

    def api_call(self, api_code: int, data: dict = None,
                 user_no: int = None, name: str = None):
        """
        POST /api 호출 래퍼.
        name: Locust 통계에 표시될 이름 (기본: api_code 번호)
        """
        if user_no is None:
            user_no = getattr(self, "user_no", random_user_no())
        payload = api_payload(user_no, api_code, data)
        request_name = name or f"[{api_code}]"
        return self.client.post(
            API_ENDPOINT,
            json=payload,
            name=request_name,
        )

    def setup_test_user(self):
        """테스트 유저 생성 → 로그인. on_start에서 호출."""
        self.user_no = random_user_no()

        # 유저 생성 (이미 있으면 무시)
        resp = self.api_call(ApiCode.CREATE_USER, name="[1003] create_user")
        # 로그인
        resp = self.api_call(ApiCode.LOGIN, name="[1010] login")
        return resp

    def grant_hero(self, hero_idx: int = 1001):
        """테스트용 영웅 부여"""
        return self.api_call(
            ApiCode.HERO_GRANT,
            {"hero_idx": hero_idx},
            name="[8002] hero_grant",
        )

    def train_units(self, unit_idx: int = 401, count: int = 100):
        """테스트용 유닛 훈련 요청"""
        return self.api_call(
            ApiCode.UNIT_TRAIN,
            {"unit_idx": unit_idx, "count": count},
            name="[4002] unit_train",
        )

    def create_march(self, units: dict, target_x: int = 50, target_y: int = 50,
                     target_type: str = "npc", npc_id: int = 1, hero_idx: int = None):
        """행군 생성"""
        data = {
            "units": units,
            "target_x": target_x,
            "target_y": target_y,
            "target_type": target_type,
        }
        if target_type == "npc":
            data["npc_id"] = npc_id
        if hero_idx:
            data["hero_idx"] = hero_idx
        return self.api_call(
            ApiCode.MARCH_CREATE,
            data,
            name=f"[9012] march_{target_type}",
        )
