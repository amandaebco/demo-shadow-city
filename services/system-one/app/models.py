"""Request and response schemas for POST /v1/decide (CONTRACT.md §2.3, §4.1)."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

MAX_ITEMS_PER_CALL = 256
MAX_MEMORY_ITEMS = 5
MAX_REASON_CHARS = 140


class Mode(str, Enum):
    walk = "walk"
    motorcycle = "motorcycle"
    car = "car"
    transjakarta = "transjakarta"
    krl = "krl"
    mrt = "mrt"
    ojol = "ojol"


class QuestionType(str, Enum):
    mode_choice = "mode_choice"
    departure_shift = "departure_shift"
    trip_cancel = "trip_cancel"
    route_choice = "route_choice"


class DecidedBy(str, Enum):
    gemma_system_one = "gemma-system-one"
    gemini_system_two = "gemini-system-two"
    rule_fallback = "rule-fallback"


class OptionDetail(BaseModel):
    est_minutes: float = Field(ge=0)
    cost_idr: int = Field(ge=0)
    flooded_on_route: bool = False


class DecisionContext(BaseModel):
    persona_summary: str
    cost_sensitivity: float = Field(ge=0, le=1)
    time_sensitivity: float = Field(ge=0, le=1)
    memory: list[str] = Field(default_factory=list, max_length=MAX_MEMORY_ITEMS)
    options_detail: dict[Mode, OptionDetail]
    active_policies: list[str] = Field(default_factory=list)
    active_events: list[str] = Field(default_factory=list)


class DecisionRequestItem(BaseModel):
    request_id: str
    scenario_id: str
    tick: int = Field(ge=0)
    persona_id: str
    cluster_id: str
    question_type: QuestionType
    options: list[Mode] = Field(min_length=1)
    context: DecisionContext

    @model_validator(mode="after")
    def check_options(self) -> "DecisionRequestItem":
        # Only mode_choice is in scope until Layer 7 (CONTRACT.md §10.4).
        if self.question_type is not QuestionType.mode_choice:
            raise ValueError(f"question_type '{self.question_type.value}' is not supported yet")
        if len(set(self.options)) != len(self.options):
            raise ValueError("options must not contain duplicates")
        missing = [o.value for o in self.options if o not in self.context.options_detail]
        if missing:
            raise ValueError(f"options_detail is missing entries for: {', '.join(missing)}")
        return self


class DecideRequest(BaseModel):
    items: list[DecisionRequestItem] = Field(min_length=1, max_length=MAX_ITEMS_PER_CALL)


class DecisionResponseItem(BaseModel):
    request_id: str
    decision_id: str
    probabilities: dict[Mode, float]
    chosen: Mode
    reason_short: str = Field(max_length=MAX_REASON_CHARS)
    decided_by: DecidedBy
    model_version: str
    latency_ms: int = Field(ge=0)


class DecideResponse(BaseModel):
    items: list[DecisionResponseItem]
