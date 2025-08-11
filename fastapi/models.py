from typing import Optional
import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, Index, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class TbStatNation(Base):
    __tablename__ = 'tb_stat_nation'
    __table_args__ = (
        Index('idx_tb_stat_nation_user_no', 'user_no'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_no: Mapped[Optional[int]] = mapped_column(Integer)
    user_no: Mapped[Optional[int]] = mapped_column(Integer)
    cr_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    tb_building: Mapped[list['TbBuilding']] = relationship('TbBuilding', back_populates='tb_stat_nation')
    tb_hero: Mapped[list['TbHero']] = relationship('TbHero', back_populates='tb_stat_nation')
    tb_research: Mapped[list['TbResearch']] = relationship('TbResearch', back_populates='tb_stat_nation')
    tb_resources: Mapped[list['TbResources']] = relationship('TbResources', back_populates='tb_stat_nation')


class TbBuilding(Base):
    __tablename__ = 'tb_building'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['tb_stat_nation.user_no'], ondelete='CASCADE', name='tb_building_ibfk_1'),
        Index('user_no_2', 'user_no', 'building_idx')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    building_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    building_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    building_status: Mapped[int] = mapped_column(Integer, nullable=False)
    building_start_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    building_end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    building_last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    tb_stat_nation: Mapped['TbStatNation'] = relationship('TbStatNation', back_populates='tb_building')


class TbHero(Base):
    __tablename__ = 'tb_hero'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['tb_stat_nation.user_no'], ondelete='CASCADE', name='tb_hero_ibfk_1'),
        Index('user_no_2', 'user_no', 'hero_idx')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_status: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_cr_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    tb_stat_nation: Mapped['TbStatNation'] = relationship('TbStatNation', back_populates='tb_hero')


class TbResearch(Base):
    __tablename__ = 'tb_research'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['tb_stat_nation.user_no'], ondelete='CASCADE', name='tb_research_ibfk_1'),
        Index('user_no_2', 'user_no', 'research_idx')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    research_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    research_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    research_status: Mapped[int] = mapped_column(Integer, nullable=False)
    research_start_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    research_end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    research_last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    tb_stat_nation: Mapped['TbStatNation'] = relationship('TbStatNation', back_populates='tb_research')


class TbResources(Base):
    __tablename__ = 'tb_resources'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['tb_stat_nation.user_no'], ondelete='CASCADE', name='tb_resources_ibfk_1'),
        Index('user_no', 'user_no', unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    food: Mapped[Optional[int]] = mapped_column(BigInteger)
    gold: Mapped[Optional[int]] = mapped_column(BigInteger)
    ruby: Mapped[Optional[int]] = mapped_column(Integer)

    tb_stat_nation: Mapped['TbStatNation'] = relationship('TbStatNation', back_populates='tb_resources')
