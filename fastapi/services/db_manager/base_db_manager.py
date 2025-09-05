# base_db_manager.py
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union, Type
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import logging
from .db_types import TableType

class BaseDBManager(ABC):
    """DB 작업 관리의 기본 클래스"""
    
    def __init__(self, db_session: Session, table_type: TableType):
        self.db = db_session
        self.table_type = table_type
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
    
    @abstractmethod
    def get_model_class(self):
        """모델 클래스 반환 (하위 클래스에서 구현)"""
        pass
    
    def _handle_db_error(self, operation: str, error: Exception) -> Dict[str, Any]:
        """DB 에러 공통 처리"""
        error_msg = f"Error in {operation} for {self.table_type.value}: {str(error)}"
        self.logger.error(error_msg)
        self.db.rollback()
        return {
            "success": False,
            "message": error_msg,
            "data": None
        }
    
    def _format_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        """응답 포맷 통일"""
        return {
            "success": success,
            "message": message,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # 공통 CRUD 메서드들
    def create(self, **kwargs) -> Dict[str, Any]:
        """레코드 생성"""
        try:
            model_class = self.get_model_class()
            new_record = model_class(**kwargs)
            
            if not self.validate_data(new_record):
                return self._format_response(False, "Invalid data provided")
            
            self.db.add(new_record)
            self.db.commit()
            self.db.refresh(new_record)
            
            return self._format_response(
                True, 
                f"{self.table_type.value.title()} created successfully",
                self._serialize_model(new_record)
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("create", e)
    
    def get_by_id(self, record_id: Union[int, str]) -> Dict[str, Any]:
        """ID로 레코드 조회"""
        try:
            model_class = self.get_model_class()
            record = self.db.query(model_class).filter(
                getattr(model_class, self._get_primary_key()) == record_id
            ).first()
            
            if not record:
                return self._format_response(
                    False, 
                    f"{self.table_type.value.title()} not found"
                )
            
            return self._format_response(
                True,
                f"{self.table_type.value.title()} retrieved successfully",
                self._serialize_model(record)
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("get_by_id", e)
    
    def update(self, record_id: Union[int, str], **kwargs) -> Dict[str, Any]:
        """레코드 업데이트"""
        try:
            model_class = self.get_model_class()
            record = self.db.query(model_class).filter(
                getattr(model_class, self._get_primary_key()) == record_id
            ).first()
            
            if not record:
                return self._format_response(
                    False,
                    f"{self.table_type.value.title()} not found"
                )
            
            # 업데이트할 필드들 적용
            for key, value in kwargs.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            
            if not self.validate_data(record):
                return self._format_response(False, "Invalid update data")
            
            self.db.commit()
            self.db.refresh(record)
            
            return self._format_response(
                True,
                f"{self.table_type.value.title()} updated successfully",
                self._serialize_model(record)
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("update", e)
    
    def delete(self, record_id: Union[int, str]) -> Dict[str, Any]:
        """레코드 삭제"""
        try:
            model_class = self.get_model_class()
            record = self.db.query(model_class).filter(
                getattr(model_class, self._get_primary_key()) == record_id
            ).first()
            
            if not record:
                return self._format_response(
                    False,
                    f"{self.table_type.value.title()} not found"
                )
            
            self.db.delete(record)
            self.db.commit()
            
            return self._format_response(
                True,
                f"{self.table_type.value.title()} deleted successfully"
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("delete", e)
    
    def get_all(self, limit: Optional[int] = None, offset: Optional[int] = None, 
               filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """모든 레코드 조회 (페이징 및 필터링 지원)"""
        try:
            model_class = self.get_model_class()
            query = self.db.query(model_class)
            
            # 필터 적용
            if filters:
                for key, value in filters.items():
                    if hasattr(model_class, key):
                        query = query.filter(getattr(model_class, key) == value)
            
            # 총 개수 계산
            total_count = query.count()
            
            # 페이징 적용
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            
            records = query.all()
            
            return self._format_response(
                True,
                f"Retrieved {len(records)} {self.table_type.value}(s)",
                {
                    "records": [self._serialize_model(record) for record in records],
                    "total_count": total_count,
                    "limit": limit,
                    "offset": offset
                }
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("get_all", e)
    
    def bulk_create(self, records_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """벌크 생성"""
        try:
            model_class = self.get_model_class()
            new_records = []
            
            for data in records_data:
                record = model_class(**data)
                if self.validate_data(record):
                    new_records.append(record)
            
            self.db.add_all(new_records)
            self.db.commit()
            
            return self._format_response(
                True,
                f"Created {len(new_records)} {self.table_type.value}(s)",
                {"created_count": len(new_records)}
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("bulk_create", e)
    
    def get_by_user(self, user_no: int, **filters) -> Dict[str, Any]:
        """사용자별 레코드 조회 (게임에서 자주 사용)"""
        try:
            model_class = self.get_model_class()
            
            if not hasattr(model_class, 'user_no'):
                return self._format_response(
                    False,
                    f"{self.table_type.value} does not support user filtering"
                )
            
            query = self.db.query(model_class).filter(model_class.user_no == user_no)
            
            # 추가 필터 적용
            for key, value in filters.items():
                if hasattr(model_class, key):
                    query = query.filter(getattr(model_class, key) == value)
            
            records = query.all()
            
            return self._format_response(
                True,
                f"Retrieved {len(records)} {self.table_type.value}(s) for user {user_no}",
                [self._serialize_model(record) for record in records]
            )
            
        except SQLAlchemyError as e:
            return self._handle_db_error("get_by_user", e)
    
    # 하위 클래스에서 구현할 추상 메서드들
    def validate_data(self, record) -> bool:
        """데이터 유효성 검증 (기본 구현)"""
        return record is not None
    
    def _get_primary_key(self) -> str:
        """프라이머리 키 필드명 반환 (기본: id)"""
        return "id"
    
    def _serialize_model(self, model) -> Dict[str, Any]:
        """모델을 딕셔너리로 직렬화 (기본 구현)"""
        if hasattr(model, '__dict__'):
            result = {}
            for key, value in model.__dict__.items():
                if not key.startswith('_'):
                    if isinstance(value, datetime):
                        result[key] = value.isoformat()
                    else:
                        result[key] = value
            return result
        return {}