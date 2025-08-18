from typing import Optional
import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, TIMESTAMP, text
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


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


class Unit(Base):
    __tablename__ = 'unit'
    __table_args__ = (
        CheckConstraint('(`death` >= 0)', name='chk_death'),
        CheckConstraint('(`field` >= 0)', name='chk_field'),
        CheckConstraint('(`healing` >= 0)', name='chk_healing'),
        CheckConstraint('(`injured` >= 0)', name='chk_injured'),
        CheckConstraint('(`ready` >= 0)', name='chk_ready'),
        CheckConstraint('(`total` >= 0)', name='chk_total'),
        CheckConstraint('(`training` >= 0)', name='chk_training'),
        CheckConstraint('(`upgrading` >= 0)', name='chk_upgrading'),
        CheckConstraint('(`wounded` >= 0)', name='chk_wounded'),
        Index('idx_unit_idx', 'unit_idx'),
        Index('idx_user_no', 'user_no'),
        Index('unique_user_unit', 'user_no', 'unit_idx', unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    ready: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    field: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    injured: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    wounded: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    healing: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    death: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    training: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    upgrading: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))


class UnitTasks(Base):
    __tablename__ = 'unit_tasks'
    __table_args__ = (
        CheckConstraint('(`quantity` > 0)', name='chk_quantity'),
        CheckConstraint('(`status` in (0,1,2,3))', name='chk_status'),
        CheckConstraint('(`task_type` in (0,1))', name='chk_task_type'),
        Index('idx_unit_idx', 'unit_idx'),
        Index('idx_user_no', 'user_no')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[int] = mapped_column(TINYINT, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("'1'"))
    status: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default=text("'0'"))
    target_unit_idx: Mapped[Optional[int]] = mapped_column(Integer)
    start_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))


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
    wood: Mapped[Optional[int]] = mapped_column(BigInteger)
    stone: Mapped[Optional[int]] = mapped_column(BigInteger)
    gold: Mapped[Optional[int]] = mapped_column(BigInteger)
    ruby: Mapped[Optional[int]] = mapped_column(Integer)

    stat_nation: Mapped['StatNation'] = relationship('StatNation', back_populates='resources')
