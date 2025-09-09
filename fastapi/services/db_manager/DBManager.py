# DBManager.py (메인 매니저)
from typing import Dict, List, Any
from sqlalchemy.orm import Session

from services.db_manager import BuildingDBManager, UnitDBManager, ResearchDBManager, BuffDBManager, ResourceDBManager


class DBManager:
    """DB 작업 관리자들의 중앙 접근점"""
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self._building_manager = None
        self._unit_manager = None
        self._research_manager = None
        self._buff_manager = None
        self._resource_manager = None
        
    
    
    
    def get_building_manager(self) -> BuildingDBManager:
        """건물 DB 관리자 반환 (싱글톤 패턴)"""
        if self._building_manager is None:
            self._building_manager = BuildingDBManager(self.db_session)
        return self._building_manager
    
    def get_unit_manager(self) -> UnitDBManager:
        """유닛 DB 관리자 반환 (싱글톤 패턴)"""
        if self._unit_manager is None:
            self._unit_manager = UnitDBManager(self.db_session)
        return self._unit_manager
    
    def get_research_manager(self) -> ResearchDBManager:
        """연구 DB 관리자 반환 (싱글톤 패턴)"""
        if self._research_manager is None:
            self._research_manager = ResearchDBManager(self.db_session)
        return self._research_manager
    
    def get_resource_manager(self) -> ResourceDBManager:
        """건물 DB 관리자 반환 (싱글톤 패턴)"""
        if self._resource_manager is None:
            self._resource_manager = ResourceDBManager(self.db_session)
        return self._resource_manager
    
    def get_buff_manager(self) -> BuffDBManager:
        """버프 DB 관리자 반환 (싱글톤 패턴)"""
        if self._buff_manager is None:
            self._buff_manager = BuffDBManager(self.db_session)
        return self._buff_manager
    
    def get_all_table_stats(self) -> Dict[str, Dict[str, Any]]:
        """모든 테이블의 통계 조회 (관리자용)"""
        result = {}
        
        managers = [
            ('building', self.get_building_manager()),
            ('unit', self.get_unit_manager()),
            ('research', self.get_research_manager()),
            ('buff', self.get_buff_manager())
        ]
        
        for name, manager in managers:
            try:
                count_result = manager.get_all(limit=0)  # 카운트만
                if count_result['success']:
                    result[name] = {
                        'total_records': count_result['data']['total_count'],
                        'table_type': manager.table_type.value
                    }
            except Exception as e:
                result[name] = {'error': str(e)}
                
        return result
    
    def commit(self):
        """트랜잭션 커밋"""
        self.db_session.commit()
    
    def rollback(self):
        """트랜잭션 롤백"""
        self.db_session.rollback()
    
    def close(self):
        """세션 종료"""
        self.db_session.close()

