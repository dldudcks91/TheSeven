from services.system.GameDataManager import GameDataManager


class HeroManager:
    """영웅 관리 매니저"""

    def __init__(self, db_manager, redis_manager):
        self._db_manager = db_manager
        self._redis_manager = redis_manager
        self.user_no = None
        self.data = {}

    async def hero_list(self) -> dict:
        """8001 - 영웅 목록 조회 (전체 도감 + 보유 여부)"""
        hero_dm = self._db_manager.get_hero_manager()
        user_heroes = hero_dm.get_user_heroes(self.user_no)
        hero_info = GameDataManager.REQUIRE_CONFIGS.get('hero', {})

        owned = {h['hero_idx']: h for h in user_heroes}

        heroes = []
        for hero_idx_str, info in hero_info.items():
            hero_idx = int(hero_idx_str)
            entry = dict(info)
            entry['hero_idx'] = hero_idx
            if hero_idx in owned:
                entry['owned'] = True
                entry['hero_lv'] = owned[hero_idx]['hero_lv']
                entry['exp'] = owned[hero_idx]['exp']
            else:
                entry['owned'] = False
                entry['hero_lv'] = 0
                entry['exp'] = 0
            heroes.append(entry)

        return {"success": True, "message": "", "data": {"heroes": heroes}}

    async def hero_grant(self) -> dict:
        """8002 - 영웅 지급 (테스트용 포트폴리오)"""
        hero_idx = self.data.get('hero_idx')
        if not hero_idx:
            return {"success": False, "message": "hero_idx 필요", "data": {}}

        hero_dm = self._db_manager.get_hero_manager()
        result = hero_dm.grant_hero(self.user_no, int(hero_idx))
        return result
