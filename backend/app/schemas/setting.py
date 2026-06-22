from datetime import datetime

from pydantic import BaseModel


class SettingResponse(BaseModel):
    key: str
    value: str
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    value: str
