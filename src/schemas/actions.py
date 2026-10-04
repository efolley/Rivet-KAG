from datetime import datetime

from pydantic import BaseModel


class ActionProposal(BaseModel):
    id: int
    session_id: str
    kind: str
    target: str
    old_value: str | None
    new_value: str
    reason: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}
