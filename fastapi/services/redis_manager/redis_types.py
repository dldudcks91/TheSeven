
from enum import Enum

class CacheType(Enum):
    """작업 타입 열거형"""
    NATION = "nation"
    ALLIANCE = "alliance"
    BUILDING = "building"
    UNIT = "unit"
    RESEARCH = "research"
    BUFF = "buff"
    RESOURCES = "resources"
    ITEM = "item"
    SHOP = "shop"
    



class TaskType(Enum):
    """작업 타입 열거형"""
    NATION = "nation"
    ALLIANCE = "alliance"
    BUILDING = "building"
    UNIT_TRAINING = "unit_training"
    RESEARCH = "research"
    BUFF = "buff"
    MARCH = "march"
    MARCH_RETURN = "march_return"

