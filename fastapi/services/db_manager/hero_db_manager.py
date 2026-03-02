from sqlalchemy.orm import Session
from models import Hero


class HeroDBManager:
    def __init__(self, db_session: Session):
        self.db_session = db_session

    def get_user_heroes(self, user_no: int) -> list:
        heroes = self.db_session.query(Hero).filter(Hero.user_no == user_no).all()
        return [self._serialize(h) for h in heroes]

    def grant_hero(self, user_no: int, hero_idx: int) -> dict:
        existing = self.db_session.query(Hero).filter(
            Hero.user_no == user_no,
            Hero.hero_idx == hero_idx
        ).first()
        if existing:
            return {"success": False, "message": "이미 보유한 영웅입니다", "data": {}}

        hero = Hero(user_no=user_no, hero_idx=hero_idx, hero_lv=1, exp=0)
        self.db_session.add(hero)
        self.db_session.commit()
        return {"success": True, "message": "영웅 지급 완료", "data": self._serialize(hero)}

    def add_hero_exp(self, user_no: int, hero_idx: int, exp_amount: int) -> dict:
        """영웅에게 EXP 추가, 레벨업 처리 (lv_up_exp = hero_lv * 100)"""
        hero = self.db_session.query(Hero).filter(
            Hero.user_no == user_no,
            Hero.hero_idx == hero_idx
        ).first()
        if not hero:
            return {"success": False, "message": "영웅을 보유하지 않았습니다", "data": {}}

        hero.exp = (hero.exp or 0) + exp_amount
        leveled_up = False
        while True:
            lv_up_exp = hero.hero_lv * 100
            if hero.exp >= lv_up_exp:
                hero.exp -= lv_up_exp
                hero.hero_lv += 1
                leveled_up = True
            else:
                break

        self.db_session.commit()
        return {
            "success": True,
            "message": "레벨업!" if leveled_up else "EXP 획득",
            "data": self._serialize(hero),
        }

    def _serialize(self, hero: Hero) -> dict:
        return {
            "hero_idx": hero.hero_idx,
            "hero_lv": hero.hero_lv,
            "exp": hero.exp or 0,
        }
