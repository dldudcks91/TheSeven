from pydantic import BaseModel
from typing import Dict, Any

class ApiRequest(BaseModel):
    api_code: int
    data: Dict[str, Any]