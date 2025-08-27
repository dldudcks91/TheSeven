
from enum import Enum

class TaskType(Enum):
    """작업 타입 열거형"""
    BUILDING = "building"
    UNIT_TRAINING = "unit_training"
    RESEARCH = "research"
    BUFF = "buff"