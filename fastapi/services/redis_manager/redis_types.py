
from enum import Enum

class CacheType(Enum):
    """작업 타입 열거형"""
    BUILDING = "building"
    UNIT = "unit"
    RESEARCH = "research"
    BUFF = "buff"
    RESOURCES = "resources"



class TaskType(Enum):
    """작업 타입 열거형"""
    BUILDING = "building"
    UNIT_TRAINING = "unit_training"
    RESEARCH = "research"
    BUFF = "buff"

