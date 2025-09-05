# db_types.py
from enum import Enum

class DBOperation(Enum):
    """DB 작업 타입 열거형"""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    BULK_INSERT = "bulk_insert"
    BULK_UPDATE = "bulk_update"

class TableType(Enum):
    """테이블 타입 열거형"""
    BUILDING = "building"
    UNIT = "unit"
    RESEARCH = "research"
    USER = "user"
    BUFF = "buff"