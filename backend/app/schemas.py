"""Pydantic schemas for the API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

class ORMModel(BaseModel):
    """Base for schemas validated from SQLAlchemy ORM objects."""
    model_config = ConfigDict(from_attributes=True)


class GoalOut(BaseModel):
    code: str
    name: str
    description: str


class PackageSummary(BaseModel):
    code: str
    goal_code: str
    level: str
    name: str
    price_kzt: float
    items_count: int
    duration_min: int


class CatalogOut(BaseModel):
    goals: list[GoalOut]
    packages: list[PackageSummary]


class CheckupRequest(BaseModel):
    goal_code: str = Field(pattern=r"^[a-z_0-9]+$")
    level: Literal["min", "rec", "max"] = "rec"
    sex: Literal["f", "m"] = "f"
    age: int | None = Field(default=None, ge=1, le=120)
    patient_id: str | None = None
    complaints: str | None = Field(default=None, max_length=4000)
    session_id: str | None = None
    # constructor overrides: remove/add items
    exclude: list[str] = Field(default_factory=list, max_length=100)
    include: list[str] = Field(default_factory=list, max_length=100)


class CheckupItemOut(BaseModel):
    test_code: str
    name: str
    label: str
    price_kzt: float
    include: bool
    skipped: bool
    skip_reason: str | None
    note: str | None
    station: str
    prep: str | None
    duration_min: int


class CheckupOut(BaseModel):
    goal_code: str
    level: str
    package_code: str
    package_name: str
    package_price_kzt: float
    dedup_saved_kzt: float
    personal_price_kzt: float
    items: list[CheckupItemOut]
    route: list[dict[str, Any]]
    total_duration_min: int
    age_extras: list[str]
    risk_notes: list[str]
    repeat_soon: list[str]
    red_flags: list[str]
    stop_message: str | None


class ResultOut(ORMModel):
    id: str
    indicator_code: str
    value_text: str | None
    unit: str | None
    reference: str | None
    exam_date: date | None
    status: str | None
    valid_until: date | None
    source: str
    confirmation: str
    flag: str | None


class PatientOut(ORMModel):
    id: str
    phone: str | None
    first_name: str
    last_name: str | None
    sex: str
    birth_year: int | None
    family_id: str | None
    consent_health: bool
    created_at: datetime


class PatientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str | None = None
    sex: Literal["f", "m"] = "f"
    birth_year: int | None = None
    phone: str | None = None
    consent_health: bool = False


class HealthMapOut(BaseModel):
    patient: PatientOut
    results: list[ResultOut]
    repeat_soon: list[dict]
    trends: list[dict]


class PdfRowIn(BaseModel):
    name: str
    value: str | None = None
    unit: str | None = None
    reference: str | None = None
    date: str | None = None
    remove: bool = False


class PdfConfirmRequest(BaseModel):
    patient_id: str
    rows: list[PdfRowIn] = Field(default_factory=list)


class PdfUploadOut(BaseModel):
    file_id: str
    kind: str
    report_date: str | None
    provider: str
    model: str
    pipeline_ms: int
    rows: list[dict]
    ok_count: int
    flagged_count: int


class PdfConfirmOut(BaseModel):
    saved: int
    skipped: int
    flagged: list[dict]
    healthmap_saved: list[str]


class BookingRequest(BaseModel):
    patient_id: str
    visit_date: date
    checkup: dict[str, Any]
    channel: str = "web"
    consent: bool = False
    phone: str | None = None
    pair_name: str | None = None  # partner first name for pair offer


class BookingOut(ORMModel):
    id: str
    patient_id: str
    visit_date: date
    status: str
    total_kzt: float
    dedup_saved_kzt: float
    channel: str
    created_at: datetime


class EventIn(BaseModel):
    session_id: str | None = None
    step: str = Field(max_length=40)
    meta: dict[str, Any] | None = None


class LlmStatus(BaseModel):
    provider: str
    model: str
    base_url: str
    can_parse_pdf: bool
    note: str
