"""Schemas from CONTRACT.md §2.1 (Persona) and §2.2 (Scenario)."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MIN_POPULATION, MAX_POPULATION = 10, 20000
LAST_TICK = 203


class Mode(str, Enum):
    walk = "walk"
    motorcycle = "motorcycle"
    car = "car"
    transjakarta = "transjakarta"
    krl = "krl"
    mrt = "mrt"
    ojol = "ojol"


class IncomeBand(str, Enum):
    low = "low"
    lower_middle = "lower_middle"
    middle = "middle"
    upper_middle = "upper_middle"
    high = "high"


class PolicyType(str, Enum):
    parking_tariff = "parking_tariff"
    transit_fare = "transit_fare"
    road_closure = "road_closure"


class EventType(str, Enum):
    flood = "flood"


class ScenarioStatus(str, Enum):
    queued = "queued"
    generating_population = "generating_population"
    running = "running"
    analyzing = "analyzing"
    completed = "completed"
    failed = "failed"


class Policy(BaseModel):
    # Only parking_tariff fields are spelled out in the contract; allow extra fields for the others.
    model_config = ConfigDict(extra="allow")
    type: PolicyType
    zone: str | None = None
    change_ratio: float | None = Field(default=None, ge=-1)


class Event(BaseModel):
    type: EventType
    area_id: str
    start_tick: int = Field(ge=0, le=LAST_TICK)
    end_tick: int = Field(ge=0, le=LAST_TICK)
    depth_cm: int = Field(ge=0)

    @model_validator(mode="after")
    def check_ticks(self) -> "Event":
        if self.end_tick < self.start_tick:
            raise ValueError("end_tick must not be before start_tick")
        return self


class ScenarioCreate(BaseModel):
    """POST /v1/scenarios body: a Scenario without id, status, progress, timestamps."""

    name: str = Field(min_length=1, max_length=200)
    base_scenario_id: str | None = None
    seed: int = Field(ge=0)
    population_size: int = Field(ge=MIN_POPULATION, le=MAX_POPULATION)
    policies: list[Policy] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)


class Place(BaseModel):
    kelurahan: str
    lat: float
    lng: float


class Persona(BaseModel):
    persona_id: str
    cluster_id: str
    is_cluster_representative: bool = True  # CONTRACT.md v1.7, §4.6
    population_id: str
    home: Place
    work: Place
    age: int = Field(ge=0, le=120)
    occupation: str
    income_band: IncomeBand
    vehicles: list[Mode]
    usual_mode: Mode
    usual_departure_tick: int = Field(ge=0, le=LAST_TICK)
    cost_sensitivity: float = Field(ge=0, le=1)
    time_sensitivity: float = Field(ge=0, le=1)
    profile_summary: str
    memory: list[str] = Field(default_factory=list, max_length=5)
