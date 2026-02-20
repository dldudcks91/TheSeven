from typing import Optional
import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, Index, Integer, String, TIMESTAMP, Text, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class Alliance(Base):
    __tablename__ = 'alliance'
    __table_args__ = (
        Index('alliance_id', 'alliance_id', unique=True),
        Index('name', 'name', unique=True)
    )

    alliance_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    leader_no: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'1'"))
    exp: Mapped[Optional[int]] = mapped_column(BigInteger, server_default=text("'0'"))
    join_type: Mapped[Optional[str]] = mapped_column(String(10), server_default=text("'free'"))
    notice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notice_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))


class AllianceApplication(Base):
    __tablename__ = 'alliance_application'

    alliance_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))


class AllianceMember(Base):
    __tablename__ = 'alliance_member'

    alliance_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'4'"))
    donated_exp: Mapped[Optional[int]] = mapped_column(BigInteger, server_default=text("'0'"))
    donated_coin: Mapped[Optional[int]] = mapped_column(BigInteger, server_default=text("'0'"))
    joined_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))


class AllianceResearch(Base):
    __tablename__ = 'alliance_research'

    alliance_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    research_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    current_exp: Mapped[Optional[int]] = mapped_column(BigInteger, server_default=text("'0'"))
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)


class AllianceActiveResearch(Base):
    __tablename__ = 'alliance_active_research'

    alliance_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    research_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    activated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    activated_by: Mapped[int] = mapped_column(Integer, nullable=False)


class Buff(Base):
    __tablename__ = 'buff'

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[int] = mapped_column(Integer, nullable=False)
    buff_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class IDCounter(Base):
    __tablename__ = 'id_counter'
    __table_args__ = (
        Index('counter_type', 'counter_type', unique=True),
        Index('idx_counter_type', 'counter_type')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    counter_type: Mapped[str] = mapped_column(String(50, 'utf8mb4_unicode_ci'), nullable=False)
    current_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("'0'"))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))


class Item(Base):
    __tablename__ = 'item'

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    cached_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class StatNation(Base):
    __tablename__ = 'stat_nation'
    __table_args__ = (
        Index('idx_tb_stat_nation_user_no', 'user_no'),
        Index('user_no_UNIQUE', 'user_no', unique=True)
    )

    account_no: Mapped[int] = mapped_column(Integer, nullable=False)
    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    cr_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_dt: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    building: Mapped[list['Building']] = relationship('Building', back_populates='stat_nation')
    hero: Mapped[list['Hero']] = relationship('Hero', back_populates='stat_nation')
    research: Mapped[list['Research']] = relationship('Research', back_populates='stat_nation')
    resources: Mapped[list['Resources']] = relationship('Resources', back_populates='stat_nation')


class Unit(Base):
    __tablename__ = 'unit'

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    total: Mapped[Optional[int]] = mapped_column(Integer)
    ready: Mapped[Optional[int]] = mapped_column(Integer)
    training: Mapped[Optional[int]] = mapped_column(Integer)
    upgrading: Mapped[Optional[int]] = mapped_column(Integer)
    field: Mapped[Optional[int]] = mapped_column(Integer)
    injured: Mapped[Optional[int]] = mapped_column(Integer)
    wounded: Mapped[Optional[int]] = mapped_column(Integer)
    healing: Mapped[Optional[int]] = mapped_column(Integer)
    death: Mapped[Optional[int]] = mapped_column(Integer)
    training_end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    cached_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class UserMission(Base):
    __tablename__ = 'user_mission'

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_completed: Mapped[Optional[int]] = mapped_column(Integer)
    is_claimed: Mapped[Optional[int]] = mapped_column(Integer)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    claimed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class Building(Base):
    __tablename__ = 'building'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['stat_nation.user_no'], ondelete='CASCADE', name='building_ibfk_1'),
        Index('user_no_2', 'user_no', 'building_idx')
    )

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    building_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
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

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    hero_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    hero_lv: Mapped[int] = mapped_column(Integer, nullable=False)
    exp: Mapped[Optional[int]] = mapped_column(Integer)

    stat_nation: Mapped['StatNation'] = relationship('StatNation', back_populates='hero')


class Research(Base):
    __tablename__ = 'research'
    __table_args__ = (
        ForeignKeyConstraint(['user_no'], ['stat_nation.user_no'], ondelete='CASCADE', name='research_ibfk_1'),
        Index('user_no_2', 'user_no', 'research_idx')
    )

    user_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
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