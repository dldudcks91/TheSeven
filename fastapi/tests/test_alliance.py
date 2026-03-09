"""
연맹 API 테스트
- 7001: 연맹 정보 조회
- 7002: 연맹 생성
- 7003: 연맹 가입
- 7004: 연맹 탈퇴
- 7005: 연맹 검색
- 7006: 멤버 목록
- 7007: 멤버 추방
- 7008: 직책 변경
- 7009: 가입 신청 목록
- 7010: 가입 승인/거절
- 7011: 기부
- 7012: 가입 방식 변경
- 7013: 연맹 해산
- 7014: 공지사항 조회
- 7015: 공지사항 작성
- 7016: 연구 목록
- 7017: 연구 선택
- 버프 통합 테스트
"""
import pytest
import json
from datetime import datetime


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------
async def call_api(client, user_no, api_code, data=None):
    """API 호출 단축 함수"""
    resp = await client.post("/api", json={
        "user_no": user_no,
        "api_code": api_code,
        "data": data or {}
    })
    return resp.json()


async def setup_nation(fake_redis, user_no, alliance_no=None, alliance_position=None):
    """유저 nation 데이터를 Redis에 세팅 (Hash 구조, 필드별 JSON 직렬화)"""
    hash_key = f"user_data:{user_no}:nation"
    data = {
        "user_no": user_no,
        "name": f"TestUser{user_no}",
        "hq_lv": 1,
        "power": 0,
        "alliance_no": alliance_no,
        "alliance_position": alliance_position,
    }
    hash_data = {str(k): json.dumps(v, default=str) for k, v in data.items()}
    await fake_redis.delete(hash_key)
    await fake_redis.hset(hash_key, mapping=hash_data)
    await fake_redis.expire(hash_key, 3600)


async def setup_resources(fake_redis, user_no, food=100000, wood=100000, stone=100000, gold=100000, ruby=1000):
    """Redis에 자원 세팅"""
    hash_key = f"user_data:{user_no}:resources"
    await fake_redis.hset(hash_key, mapping={
        "food": str(food),
        "wood": str(wood),
        "stone": str(stone),
        "gold": str(gold),
        "ruby": str(ruby),
    })
    await fake_redis.expire(hash_key, 3600)


async def create_alliance_via_api(client, user_no, name="TestAlliance", join_type="free"):
    """API를 통해 연맹 생성 (헬퍼)"""
    result = await call_api(client, user_no, 7002, {
        "name": name,
        "join_type": join_type
    })
    return result


# ---------------------------------------------------------------------------
# 유저 번호 상수
# ---------------------------------------------------------------------------
USER_LEADER = 99999
USER_MEMBER_A = 88888
USER_MEMBER_B = 77777
USER_OUTSIDER = 66666


# ===========================================================================
# 7002: 연맹 생성
# ===========================================================================
class TestAllianceCreate:
    @pytest.mark.asyncio
    async def test_create_success(self, client, fake_redis, create_test_user, test_user_no):
        """연맹 생성 성공"""
        await setup_nation(fake_redis, test_user_no)

        result = await call_api(client, test_user_no, 7002, {
            "name": "MyAlliance",
            "join_type": "free"
        })
        assert result["success"] is True
        assert result["data"]["name"] == "MyAlliance"
        assert result["data"]["alliance_no"] is not None

    @pytest.mark.asyncio
    async def test_create_duplicate_name(self, client, fake_redis, create_test_user, test_user_no):
        """중복 이름 → 실패"""
        await setup_nation(fake_redis, test_user_no)

        result1 = await call_api(client, test_user_no, 7002, {"name": "DupAlliance"})
        assert result1["success"] is True

        # 다른 유저로 동일 이름 생성 시도
        await setup_nation(fake_redis, USER_MEMBER_A)
        result2 = await call_api(client, USER_MEMBER_A, 7002, {"name": "DupAlliance"})
        assert result2["success"] is False

    @pytest.mark.asyncio
    async def test_create_already_in_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """이미 연맹에 가입된 유저 → 실패"""
        await setup_nation(fake_redis, test_user_no, alliance_no=1, alliance_position=4)

        result = await call_api(client, test_user_no, 7002, {"name": "NewAlliance"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_invalid_name(self, client, fake_redis, create_test_user, test_user_no):
        """이름 길이 제한 위반 → 실패"""
        await setup_nation(fake_redis, test_user_no)

        # 1글자 (2~20자 필요)
        result = await call_api(client, test_user_no, 7002, {"name": "A"})
        assert result["success"] is False

        # 21글자
        result2 = await call_api(client, test_user_no, 7002, {"name": "A" * 21})
        assert result2["success"] is False


# ===========================================================================
# 7001: 연맹 정보 조회
# ===========================================================================
class TestAllianceInfo:
    @pytest.mark.asyncio
    async def test_info_no_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """연맹 미가입 유저 → has_alliance=False"""
        await setup_nation(fake_redis, test_user_no)

        result = await call_api(client, test_user_no, 7001)
        assert result["success"] is True
        assert result["data"]["has_alliance"] is False

    @pytest.mark.asyncio
    async def test_info_with_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """연맹 가입 유저 → 연맹 정보 반환"""
        await setup_nation(fake_redis, test_user_no)

        create_result = await create_alliance_via_api(client, test_user_no, "InfoTestAlliance")
        assert create_result["success"] is True

        result = await call_api(client, test_user_no, 7001)
        assert result["success"] is True
        assert result["data"]["has_alliance"] is True
        assert result["data"]["my_position"] == 1  # 맹주
        assert result["data"]["alliance"]["name"] == "InfoTestAlliance"
        assert result["data"]["alliance"]["member_count"] == 1


# ===========================================================================
# 7003: 연맹 가입
# ===========================================================================
class TestAllianceJoin:
    @pytest.mark.asyncio
    async def test_join_free(self, client, fake_redis, create_test_user, test_user_no):
        """자유가입 연맹 → 즉시 가입"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "FreeJoin")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert result["success"] is True
        assert result["data"]["status"] == "joined"

    @pytest.mark.asyncio
    async def test_join_approval(self, client, fake_redis, create_test_user, test_user_no):
        """승인제 연맹 → 신청 상태"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "ApprovalJoin", "approval")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert result["success"] is True
        assert result["data"]["status"] == "applied"

    @pytest.mark.asyncio
    async def test_join_already_in_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """이미 연맹 소속 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "JoinTest1")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A, alliance_no=999, alliance_position=4)
        result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_join_nonexistent_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """존재하지 않는 연맹 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        result = await call_api(client, test_user_no, 7003, {"alliance_no": 99999})
        assert result["success"] is False


# ===========================================================================
# 7004: 연맹 탈퇴
# ===========================================================================
class TestAllianceLeave:
    @pytest.mark.asyncio
    async def test_leave_success(self, client, fake_redis, create_test_user, test_user_no):
        """일반 멤버 탈퇴 성공"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "LeaveTest")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, USER_MEMBER_A, 7004)
        assert result["success"] is True
        assert result["data"]["left"] is True

    @pytest.mark.asyncio
    async def test_leave_leader_fail(self, client, fake_redis, create_test_user, test_user_no):
        """맹주 탈퇴 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "LeaderLeave")

        result = await call_api(client, test_user_no, 7004)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_leave_no_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """연맹 미가입 상태에서 탈퇴 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        result = await call_api(client, test_user_no, 7004)
        assert result["success"] is False


# ===========================================================================
# 7005: 연맹 검색
# ===========================================================================
class TestAllianceSearch:
    @pytest.mark.asyncio
    async def test_search_all(self, client, fake_redis, create_test_user, test_user_no):
        """키워드 없이 전체 목록"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "SearchAll")

        result = await call_api(client, test_user_no, 7005)
        assert result["success"] is True
        assert len(result["data"]["alliances"]) >= 1

    @pytest.mark.asyncio
    async def test_search_keyword(self, client, fake_redis, create_test_user, test_user_no):
        """키워드 검색"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "UniqueAlpha")

        result = await call_api(client, test_user_no, 7005, {"keyword": "UniqueAlpha"})
        assert result["success"] is True
        assert len(result["data"]["alliances"]) == 1
        assert result["data"]["alliances"][0]["name"] == "UniqueAlpha"

    @pytest.mark.asyncio
    async def test_search_no_match(self, client, fake_redis, create_test_user, test_user_no):
        """매칭 없는 키워드 → 빈 배열"""
        await setup_nation(fake_redis, test_user_no)
        result = await call_api(client, test_user_no, 7005, {"keyword": "ZZZZNONEXIST"})
        assert result["success"] is True
        assert len(result["data"]["alliances"]) == 0


# ===========================================================================
# 7006: 멤버 목록
# ===========================================================================
class TestAllianceMembers:
    @pytest.mark.asyncio
    async def test_members_list(self, client, fake_redis, create_test_user, test_user_no):
        """멤버 목록 조회"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "MemberList")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, test_user_no, 7006)
        assert result["success"] is True
        assert len(result["data"]["members"]) == 2

        # 맹주가 먼저 (position 정렬)
        positions = [m["position"] for m in result["data"]["members"]]
        assert positions[0] <= positions[1]


# ===========================================================================
# 7007: 멤버 추방
# ===========================================================================
class TestAllianceKick:
    @pytest.mark.asyncio
    async def test_kick_success(self, client, fake_redis, create_test_user, test_user_no):
        """맹주가 일반 멤버 추방"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "KickTest")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, test_user_no, 7007, {"target_user_no": USER_MEMBER_A})
        assert result["success"] is True
        assert result["data"]["kicked"] is True

    @pytest.mark.asyncio
    async def test_kick_no_permission(self, client, fake_redis, create_test_user, test_user_no):
        """일반 멤버가 추방 시도 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "KickPerm")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        await setup_nation(fake_redis, USER_MEMBER_B)
        await call_api(client, USER_MEMBER_B, 7003, {"alliance_no": alliance_no})

        # 일반 멤버 A가 일반 멤버 B 추방 시도
        result = await call_api(client, USER_MEMBER_A, 7007, {"target_user_no": USER_MEMBER_B})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_kick_self(self, client, fake_redis, create_test_user, test_user_no):
        """자기 자신 추방 시도 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "KickSelf")

        result = await call_api(client, test_user_no, 7007, {"target_user_no": test_user_no})
        assert result["success"] is False


# ===========================================================================
# 7008: 직책 변경
# ===========================================================================
class TestAlliancePromote:
    @pytest.mark.asyncio
    async def test_promote_to_officer(self, client, fake_redis, create_test_user, test_user_no):
        """맹주가 일반 멤버를 간부로 승격"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "PromoteTest")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, test_user_no, 7008, {
            "target_user_no": USER_MEMBER_A,
            "new_position": 3  # 간부
        })
        assert result["success"] is True
        assert result["data"]["promoted"] is True

    @pytest.mark.asyncio
    async def test_transfer_leadership(self, client, fake_redis, create_test_user, test_user_no):
        """맹주 위임"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "LeaderTransfer")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, test_user_no, 7008, {
            "target_user_no": USER_MEMBER_A,
            "new_position": 1  # 맹주 위임
        })
        assert result["success"] is True
        assert result["data"]["new_leader"] == USER_MEMBER_A


# ===========================================================================
# 7009/7010: 가입 신청 관리
# ===========================================================================
class TestAllianceApplications:
    @pytest.mark.asyncio
    async def test_application_flow(self, client, fake_redis, create_test_user, test_user_no):
        """승인제: 신청 → 목록 조회 → 승인"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "AppFlow", "approval")
        alliance_no = create_result["data"]["alliance_no"]

        # 신청
        await setup_nation(fake_redis, USER_MEMBER_A)
        join_result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert join_result["data"]["status"] == "applied"

        # 신청 목록 조회
        list_result = await call_api(client, test_user_no, 7009)
        assert list_result["success"] is True
        assert len(list_result["data"]["applications"]) == 1
        assert list_result["data"]["applications"][0]["user_no"] == USER_MEMBER_A

        # 승인
        approve_result = await call_api(client, test_user_no, 7010, {
            "target_user_no": USER_MEMBER_A,
            "approve": True
        })
        assert approve_result["success"] is True
        assert approve_result["data"]["approved"] is True

        # 승인 후 멤버 수 확인
        members_result = await call_api(client, test_user_no, 7006)
        assert len(members_result["data"]["members"]) == 2

    @pytest.mark.asyncio
    async def test_application_reject(self, client, fake_redis, create_test_user, test_user_no):
        """가입 신청 거절"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "AppReject", "approval")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        reject_result = await call_api(client, test_user_no, 7010, {
            "target_user_no": USER_MEMBER_A,
            "approve": False
        })
        assert reject_result["success"] is True
        assert reject_result["data"]["approved"] is False

        # 거절 후 신청 목록 비어있음
        list_result = await call_api(client, test_user_no, 7009)
        assert len(list_result["data"]["applications"]) == 0


# ===========================================================================
# 7011: 기부
# ===========================================================================
class TestAllianceDonate:
    @pytest.mark.asyncio
    async def test_donate_success(self, client, fake_redis, create_test_user, test_user_no):
        """기부 성공 + 경험치/코인 획득"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=100000)
        create_result = await create_alliance_via_api(client, test_user_no, "DonateTest")
        assert create_result["success"] is True

        result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 10000,
            "research_idx": 8001
        })
        assert result["success"] is True
        assert result["data"]["exp_gained"] > 0
        assert result["data"]["donated_amount"] == 10000
        # food exp_ratio=100 → 10000 // 100 = 100 exp
        assert result["data"]["exp_gained"] == 100

    @pytest.mark.asyncio
    async def test_donate_insufficient_resources(self, client, fake_redis, create_test_user, test_user_no):
        """자원 부족 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=10)
        create_result = await create_alliance_via_api(client, test_user_no, "DonateInsuff")
        assert create_result["success"] is True

        result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 100000,
            "research_idx": 8001
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_donate_invalid_research(self, client, fake_redis, create_test_user, test_user_no):
        """존재하지 않는 연구 idx → 실패"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "DonateInvalid")
        assert create_result["success"] is True

        result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 1000,
            "research_idx": 99999
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_donate_no_alliance(self, client, fake_redis, create_test_user, test_user_no):
        """연맹 미가입 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no)

        result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 1000,
            "research_idx": 8001
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_donate_alliance_level_up(self, client, fake_redis, create_test_user, test_user_no):
        """대량 기부 → 연맹 레벨업 확인"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=10000000)
        create_result = await create_alliance_via_api(client, test_user_no, "DonateLvUp")
        assert create_result["success"] is True

        # alliance_level.csv: level 2 required_exp=1000
        # food exp_ratio=100 → 100000 food = 1000 exp → 레벨2 달성
        result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 100000,
            "research_idx": 8001
        })
        assert result["success"] is True
        assert result["data"]["leveled_up"] is True
        assert result["data"]["alliance_level"] >= 2


# ===========================================================================
# 7012: 가입 방식 변경
# ===========================================================================
class TestAllianceJoinType:
    @pytest.mark.asyncio
    async def test_change_join_type(self, client, fake_redis, create_test_user, test_user_no):
        """맹주가 가입 방식 변경"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "JoinTypeTest")

        result = await call_api(client, test_user_no, 7012, {"join_type": "approval"})
        assert result["success"] is True
        assert result["data"]["join_type"] == "approval"

    @pytest.mark.asyncio
    async def test_change_join_type_no_permission(self, client, fake_redis, create_test_user, test_user_no):
        """일반 멤버가 변경 시도 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "JoinTypePerm")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, USER_MEMBER_A, 7012, {"join_type": "approval"})
        assert result["success"] is False


# ===========================================================================
# 7013: 연맹 해산
# ===========================================================================
class TestAllianceDisband:
    @pytest.mark.asyncio
    async def test_disband_success(self, client, fake_redis, create_test_user, test_user_no):
        """맹주가 연맹 해산"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "DisbandTest")
        assert create_result["success"] is True

        result = await call_api(client, test_user_no, 7013)
        assert result["success"] is True
        assert result["data"]["disbanded"] is True

        # 해산 후 연맹 정보 조회 → 미가입 상태
        info_result = await call_api(client, test_user_no, 7001)
        assert info_result["success"] is True
        assert info_result["data"]["has_alliance"] is False

    @pytest.mark.asyncio
    async def test_disband_no_permission(self, client, fake_redis, create_test_user, test_user_no):
        """일반 멤버가 해산 시도 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "DisbandPerm")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, USER_MEMBER_A, 7013)
        assert result["success"] is False


# ===========================================================================
# 7014/7015: 공지사항
# ===========================================================================
class TestAllianceNotice:
    @pytest.mark.asyncio
    async def test_notice_write_and_read(self, client, fake_redis, create_test_user, test_user_no):
        """공지 작성 → 조회"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "NoticeTest")

        # 작성
        write_result = await call_api(client, test_user_no, 7015, {
            "notice": "Hello Alliance!"
        })
        assert write_result["success"] is True
        assert write_result["data"]["notice"]["content"] == "Hello Alliance!"

        # 조회
        read_result = await call_api(client, test_user_no, 7014)
        assert read_result["success"] is True
        assert read_result["data"]["notice"]["content"] == "Hello Alliance!"

    @pytest.mark.asyncio
    async def test_notice_write_non_leader(self, client, fake_redis, create_test_user, test_user_no):
        """일반 멤버 공지 작성 → 실패"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "NoticePerm")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, USER_MEMBER_A, 7015, {"notice": "Unauthorized"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_notice_write_officer(self, client, fake_redis, create_test_user, test_user_no):
        """간부(position 3)는 공지 작성 가능 (can_notice=1)"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "NoticeOfficer")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        # 맹주가 간부로 승격
        await call_api(client, test_user_no, 7008, {
            "target_user_no": USER_MEMBER_A,
            "new_position": 3
        })

        # 간부가 공지 작성
        result = await call_api(client, USER_MEMBER_A, 7015, {"notice": "Officer Notice"})
        assert result["success"] is True
        assert result["data"]["notice"]["content"] == "Officer Notice"


# ===========================================================================
# 7016/7017: 연구
# ===========================================================================
class TestAllianceResearch:
    @pytest.mark.asyncio
    async def test_research_list(self, client, fake_redis, create_test_user, test_user_no):
        """연구 목록 조회"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "ResearchList")

        result = await call_api(client, test_user_no, 7016)
        assert result["success"] is True
        assert len(result["data"]["research_list"]) == 3  # 8001, 8002, 8003
        for r in result["data"]["research_list"]:
            assert r["level"] == 0
            assert r["max_level"] == 5

    @pytest.mark.asyncio
    async def test_research_select_no_exp(self, client, fake_redis, create_test_user, test_user_no):
        """경험치 미충족 → 활성 연구로만 지정"""
        await setup_nation(fake_redis, test_user_no)
        await create_alliance_via_api(client, test_user_no, "ResSelect")

        result = await call_api(client, test_user_no, 7017, {"research_idx": 8001})
        assert result["success"] is True
        assert result["data"]["leveled_up"] is False
        assert result["data"]["research_idx"] == 8001

    @pytest.mark.asyncio
    async def test_research_select_with_levelup(self, client, fake_redis, create_test_user, test_user_no):
        """경험치 충족 → 연구 레벨업"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=10000000)
        create_result = await create_alliance_via_api(client, test_user_no, "ResLvUp")
        assert create_result["success"] is True

        # 기부로 연구 경험치 적립 (research 8001, food exp_ratio=100)
        # alliance_research.csv: 8001 lv1 required_exp=1000 → 100000 food = 1000 exp
        donate_result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 100000,
            "research_idx": 8001
        })
        assert donate_result["success"] is True
        assert donate_result["data"]["exp_gained"] >= 1000

        # 연구 선택 → 레벨업 실행
        select_result = await call_api(client, test_user_no, 7017, {"research_idx": 8001})
        assert select_result["success"] is True
        assert select_result["data"]["leveled_up"] is True
        assert select_result["data"]["level"] >= 1

    @pytest.mark.asyncio
    async def test_research_select_no_permission(self, client, fake_redis, create_test_user, test_user_no):
        """일반 멤버가 연구 선택 → 실패 (간부 이상만 가능)"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "ResPerm")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        result = await call_api(client, USER_MEMBER_A, 7017, {"research_idx": 8001})
        assert result["success"] is False


# ===========================================================================
# 버프 통합 테스트
# ===========================================================================
class TestAllianceBuff:
    @pytest.mark.asyncio
    async def test_create_applies_level_buff(self, client, fake_redis, create_test_user, test_user_no):
        """연맹 생성 시 맹주에게 레벨 버프 적용"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "BuffTest")
        assert create_result["success"] is True
        alliance_no = create_result["data"]["alliance_no"]

        # buff 확인: alliance level buff = buff_idx 103, target_type = building
        buff_key = f"user_data:{test_user_no}:buff"
        building_buff = await fake_redis.hget(buff_key, "building")
        assert building_buff is not None

        buff_data = json.loads(building_buff)
        source_key = f"alliance:{alliance_no}"
        assert source_key in buff_data
        assert buff_data[source_key]["buff_idx"] == 103
        assert buff_data[source_key]["value"] == 1

    @pytest.mark.asyncio
    async def test_join_applies_buff(self, client, fake_redis, create_test_user, test_user_no):
        """가입 시 멤버에게 버프 적용"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "JoinBuff")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        join_result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert join_result["success"] is True

        # 가입한 멤버의 버프 확인
        buff_key = f"user_data:{USER_MEMBER_A}:buff"
        building_buff = await fake_redis.hget(buff_key, "building")
        assert building_buff is not None

        buff_data = json.loads(building_buff)
        source_key = f"alliance:{alliance_no}"
        assert source_key in buff_data

    @pytest.mark.asyncio
    async def test_leave_removes_buff(self, client, fake_redis, create_test_user, test_user_no):
        """탈퇴 시 버프 제거"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "LeaveBuff")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        # 버프 존재 확인
        buff_key = f"user_data:{USER_MEMBER_A}:buff"
        building_buff = await fake_redis.hget(buff_key, "building")
        assert building_buff is not None

        # 탈퇴
        await call_api(client, USER_MEMBER_A, 7004)

        # 버프 제거 확인
        building_buff_after = await fake_redis.hget(buff_key, "building")
        if building_buff_after:
            buff_data = json.loads(building_buff_after)
            source_key = f"alliance:{alliance_no}"
            assert source_key not in buff_data

    @pytest.mark.asyncio
    async def test_kick_removes_buff(self, client, fake_redis, create_test_user, test_user_no):
        """추방 시 버프 제거"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "KickBuff")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        # 추방
        await call_api(client, test_user_no, 7007, {"target_user_no": USER_MEMBER_A})

        # 버프 제거 확인
        buff_key = f"user_data:{USER_MEMBER_A}:buff"
        building_buff = await fake_redis.hget(buff_key, "building")
        if building_buff:
            buff_data = json.loads(building_buff)
            source_key = f"alliance:{alliance_no}"
            assert source_key not in buff_data

    @pytest.mark.asyncio
    async def test_disband_removes_all_buffs(self, client, fake_redis, create_test_user, test_user_no):
        """해산 시 모든 멤버 버프 제거"""
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "DisbandBuff")
        alliance_no = create_result["data"]["alliance_no"]

        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        # 해산
        await call_api(client, test_user_no, 7013)

        # 양쪽 다 버프 제거 확인
        for user_no in [test_user_no, USER_MEMBER_A]:
            buff_key = f"user_data:{user_no}:buff"
            building_buff = await fake_redis.hget(buff_key, "building")
            if building_buff:
                buff_data = json.loads(building_buff)
                source_key = f"alliance:{alliance_no}"
                assert source_key not in buff_data

    @pytest.mark.asyncio
    async def test_research_levelup_applies_buff(self, client, fake_redis, create_test_user, test_user_no):
        """연구 레벨업 → 모든 멤버에게 연구 버프 적용"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=10000000)
        create_result = await create_alliance_via_api(client, test_user_no, "ResBuff")
        alliance_no = create_result["data"]["alliance_no"]

        # 멤버 가입
        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        # 기부 (research 8001 → buff_idx 205, target_type = unit)
        await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 100000,
            "research_idx": 8001
        })

        # 연구 선택 → 레벨업
        select_result = await call_api(client, test_user_no, 7017, {"research_idx": 8001})
        assert select_result["success"] is True
        assert select_result["data"]["leveled_up"] is True

        # 맹주 연구 버프 확인 (buff_idx 205, target_type = unit)
        buff_key = f"user_data:{test_user_no}:buff"
        unit_buff = await fake_redis.hget(buff_key, "unit")
        assert unit_buff is not None
        buff_data = json.loads(unit_buff)
        source_key = f"alliance_research:8001"
        assert source_key in buff_data
        assert buff_data[source_key]["buff_idx"] == 205

        # 일반 멤버도 연구 버프 받음
        buff_key_member = f"user_data:{USER_MEMBER_A}:buff"
        unit_buff_member = await fake_redis.hget(buff_key_member, "unit")
        assert unit_buff_member is not None
        buff_data_member = json.loads(unit_buff_member)
        assert source_key in buff_data_member

    @pytest.mark.asyncio
    async def test_new_member_gets_existing_research_buff(self, client, fake_redis, create_test_user, test_user_no):
        """연구 레벨업 후 신규 가입 멤버도 연구 버프 받음"""
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=10000000)
        create_result = await create_alliance_via_api(client, test_user_no, "NewMemberBuff")
        alliance_no = create_result["data"]["alliance_no"]

        # 기부 + 연구 레벨업
        await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 100000,
            "research_idx": 8001
        })
        select_result = await call_api(client, test_user_no, 7017, {"research_idx": 8001})
        assert select_result["data"]["leveled_up"] is True

        # 신규 멤버 가입
        await setup_nation(fake_redis, USER_MEMBER_A)
        await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})

        # 신규 멤버의 연구 버프 확인
        buff_key = f"user_data:{USER_MEMBER_A}:buff"
        unit_buff = await fake_redis.hget(buff_key, "unit")
        assert unit_buff is not None
        buff_data = json.loads(unit_buff)
        assert "alliance_research:8001" in buff_data


# ===========================================================================
# 통합 플로우 테스트
# ===========================================================================
class TestAllianceFlow:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, client, fake_redis, create_test_user, test_user_no):
        """전체 플로우: 생성 → 가입 → 기부 → 연구 → 탈퇴"""
        # 1. 연맹 생성
        await setup_nation(fake_redis, test_user_no)
        await setup_resources(fake_redis, test_user_no, food=10000000)
        create_result = await create_alliance_via_api(client, test_user_no, "FullFlow")
        assert create_result["success"] is True
        alliance_no = create_result["data"]["alliance_no"]

        # 2. 멤버 가입
        await setup_nation(fake_redis, USER_MEMBER_A)
        join_result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert join_result["data"]["status"] == "joined"

        # 3. 멤버 목록 확인
        members = await call_api(client, test_user_no, 7006)
        assert len(members["data"]["members"]) == 2

        # 4. 기부
        donate_result = await call_api(client, test_user_no, 7011, {
            "resource_type": "food",
            "amount": 100000,
            "research_idx": 8001
        })
        assert donate_result["success"] is True

        # 5. 연구 선택 + 레벨업
        select_result = await call_api(client, test_user_no, 7017, {"research_idx": 8001})
        assert select_result["success"] is True

        # 6. 멤버 탈퇴
        leave_result = await call_api(client, USER_MEMBER_A, 7004)
        assert leave_result["success"] is True

        # 7. 탈퇴 후 멤버 수 확인
        members_after = await call_api(client, test_user_no, 7006)
        assert len(members_after["data"]["members"]) == 1

    @pytest.mark.asyncio
    async def test_approval_join_full_flow(self, client, fake_redis, create_test_user, test_user_no):
        """승인제 플로우: 생성(승인제) → 신청 → 승인 → 추방"""
        # 1. 승인제 연맹 생성
        await setup_nation(fake_redis, test_user_no)
        create_result = await create_alliance_via_api(client, test_user_no, "ApprovalFlow", "approval")
        alliance_no = create_result["data"]["alliance_no"]

        # 2. 가입 신청
        await setup_nation(fake_redis, USER_MEMBER_A)
        join_result = await call_api(client, USER_MEMBER_A, 7003, {"alliance_no": alliance_no})
        assert join_result["data"]["status"] == "applied"

        # 3. 승인
        approve_result = await call_api(client, test_user_no, 7010, {
            "target_user_no": USER_MEMBER_A,
            "approve": True
        })
        assert approve_result["data"]["approved"] is True

        # 4. 멤버 확인
        members = await call_api(client, test_user_no, 7006)
        assert len(members["data"]["members"]) == 2

        # 5. 추방
        kick_result = await call_api(client, test_user_no, 7007, {"target_user_no": USER_MEMBER_A})
        assert kick_result["data"]["kicked"] is True

        # 6. 추방 후 멤버 수
        members_after = await call_api(client, test_user_no, 7006)
        assert len(members_after["data"]["members"]) == 1
