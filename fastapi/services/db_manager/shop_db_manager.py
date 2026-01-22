from datetime import datetime
from typing import Optional, Dict, Any, List
import logging


class ShopDBManager:
    """
    Shop DB 관리자
    """
    
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(self.__class__.__name__)