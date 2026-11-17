from pydantic import BaseModel, Field
class BudgetInput(BaseModel):
    dataset_id: int
    total_epsilon: float = Field(ge=0, le=1000)
    clip_bound: float = Field(gt=0, le=1000000)
class GrantInput(BaseModel):
    consultant_id: int
    dataset_id: int
    max_epsilon: float = Field(gt=0, le=100)
class DpQueryInput(BaseModel):
    dataset_id: int
    week_start: str = Field(min_length=10, max_length=10)
    epsilon: float = Field(gt=0, le=100)
    request_key: str = Field(min_length=8, max_length=80)
