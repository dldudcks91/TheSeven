from pydantic import BaseModel
from typing import Dict, Any

class ApiRequest(BaseModel):
    user_no: int
    api_code: int
    data: Dict[str, Any]