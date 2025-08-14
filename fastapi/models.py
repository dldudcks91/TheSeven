from typing import Optional
import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, Index, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = 'item'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    cnt: Mapped[Optional[int]] = mapped_column(Integer)
    cr_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class StatNation(Base):
    __tablename__ = 'stat_nation'
    __table_args__ = (
        Index('idx_tb_stat_nation_user_no', 'user_no'),
        Index('user_no_UNIQUE', 'user_no', unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_no: Mapped[int] = mapped_column(Integer, nullable=False)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    cr_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    building: Mapped[list['Building']] = relationship('Building', back_populates='stat_nation')
    hero: Mapped[list['Hero']] = relationship('Hero', back_populates='stat_nation')
    research: Mapped[list['Research']] = relationship('Research', back_populates='stat_nation')
    resources: Mapped[list['Resources']] = relationship('Resources', back_populates='stat_nation')


class Building(Base):
    __tablename__ = 'building'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['stat_nation.user_no'], ondelete='CASCADE', name='building_ibfk_1'),
        Index('user_no_2', 'user_no', 'building_idx')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    building_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    building_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    stat_nation: Mapped['StatNation'] = relationship('StatNation', back_populates='building')


class Hero(Base):
    __tablename__ = 'hero'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['stat_nation.user_no'], ondelete='CASCADE', name='hero_ibfk_1'),
        Index('user_no_2', 'user_no', 'hero_idx')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_status: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_cr_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    stat_nation: Mapped['StatNation'] = relationship('StatNation', back_populates='hero')


class Research(Base):
    __tablename__ = 'research'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['stat_nation.user_no'], ondelete='CASCADE', name='research_ibfk_1'),
        Index('user_no_2', 'user_no', 'research_idx')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    research_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    research_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    stat_nation: Mapped['StatNation'] = relationship('StatNation', back_populates='research')


class Resources(Base):
    __tablename__ = 'resources'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['stat_nation.user_no'], ondelete='CASCADE', name='resources_ibfk_1'),
        Index('user_no', 'user_no', unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    food: Mapped[Optional[int]] = mapped_column(BigInteger)
    gold: Mapped[Optional[int]] = mapped_column(BigInteger)
    ruby: Mapped[Optional[int]] = mapped_column(Integer)

    stat_nation: Mapped['StatNation'] = relationship('StatNation', back_populates='resources')
