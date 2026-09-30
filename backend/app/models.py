"""SQLAlchemy models — the patient health map, checkups, bookings, funnel events.

Rules (packages, indicators, validity) live in CSV data, not here — doctors can
edit them without a developer. The DB stores facts about patients.
"""
from __future__ import annotations

import enum
import json
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, enum.Enum):
    ok = "ok"
    borderline = "borderline"
    abnormal = "abnormal"


class ResultSource(str, enum.Enum):
    pdf = "pdf"
    manual = "manual"
    clinic = "clinic"


class ResultConfirmation(str, enum.Enum):
    extracted = "extracted"  # in pipeline, not yet confirmed
    pending = "pending"      # waiting for patient
    confirmed = "confirmed"  # patient confirmed -> part of the health map
    corrected = "corrected"  # patient corrected during confirmation


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    canceled = "canceled"
    done = "done"


class BaseMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Patient(Base, BaseMixin):
    __tablename__ = "patients"

    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    sex: Mapped[str] = mapped_column(String(1), default="f")  # f | m
    birth_year: Mapped[int | None] = mapped_column(Integer)
    tg_id: Mapped[str | None] = mapped_column(String(64))
    family_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"))
    consent_health: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list[Result]] = relationship(back_populates="patient")
    bookings: Mapped[list[Booking]] = relationship(back_populates="patient")


class Result(Base, BaseMixin):
    """One measured value. Only confirmed rows form the health map (dedup engine reads these)."""

    __tablename__ = "results"

    # NULL until the patient confirms the file's rows (model extracts, human confirms)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True, default=None)
    indicator_code: Mapped[str] = mapped_column(String(40), index=True)
    value_text: Mapped[str | None] = mapped_column(String(64))
    value_num: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    reference: Mapped[str | None] = mapped_column(String(120))
    exam_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[Status | None] = mapped_column(Enum(Status), default=Status.ok)
    valid_until: Mapped[date | None] = mapped_column(Date)
    source: Mapped[ResultSource] = mapped_column(Enum(ResultSource), default=ResultSource.manual)
    confirmation: Mapped[ResultConfirmation] = mapped_column(
        Enum(ResultConfirmation), default=ResultConfirmation.confirmed
    )
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id"))
    flag: Mapped[str | None] = mapped_column(String(200))  # pipeline suspicion, for humans
    raw: Mapped[str | None] = mapped_column(Text)  # LLM/extractor raw row

    patient: Mapped[Patient] = relationship(back_populates="results")
    source_file: Mapped[SourceFile | None] = relationship(back_populates="results")


class SourceFile(Base, BaseMixin):
    __tablename__ = "source_files"

    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(512))
    size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="text")  # text | scan | unknown
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    llm_provider: Mapped[str | None] = mapped_column(String(32))
    llm_model: Mapped[str | None] = mapped_column(String(64))
    pipeline_ms: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String(120))

    results: Mapped[list[Result]] = relationship(back_populates="source_file")
    checkups: Mapped[list[Checkup]] = relationship(back_populates="source_file")


class Checkup(Base, BaseMixin):
    """A computed checkup plan: package, items with reasons, prices, route."""

    __tablename__ = "checkups"

    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(32))
    goal_code: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(8), default="rec")
    package_name: Mapped[str] = mapped_column(String(120))
    package_price: Mapped[float] = mapped_column(Float, default=0)
    personal_price: Mapped[float] = mapped_column(Float, default=0)
    dedup_saved: Mapped[float] = mapped_column(Float, default=0)
    total_duration_min: Mapped[int] = mapped_column(Integer, default=0)
    red_flags: Mapped[str | None] = mapped_column(Text)  # JSON list
    snapshot: Mapped[str | None] = mapped_column(Text)  # full JSON snapshot for UI/replay
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("source_files.id"))

    source_file: Mapped[SourceFile | None] = relationship(back_populates="checkups")
    booking: Mapped[Booking | None] = relationship(back_populates="checkup", uselist=False)


class Booking(Base, BaseMixin):
    __tablename__ = "bookings"

    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    checkup_id: Mapped[str | None] = mapped_column(ForeignKey("checkups.id"))
    visit_date: Mapped[date] = mapped_column(Date)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.pending)
    total_kzt: Mapped[float] = mapped_column(Float, default=0)
    dedup_saved_kzt: Mapped[float] = mapped_column(Float, default=0)
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web | tg | phone
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pair_booking_id: Mapped[str | None] = mapped_column(String(32))  # partner's booking (pair offer)
    meta: Mapped[str | None] = mapped_column(Text)  # JSON

    patient: Mapped[Patient] = relationship(back_populates="bookings")
    checkup: Mapped[Checkup | None] = relationship(back_populates="booking")


class Event(Base, BaseMixin):
    """Funnel events: landing -> goal -> options -> constructor -> pdf -> booking_form -> booked ..."""

    __tablename__ = "events"

    session_id: Mapped[str | None] = mapped_column(String(32), index=True)
    step: Mapped[str] = mapped_column(String(40), index=True)
    meta: Mapped[str | None] = mapped_column(Text)  # JSON

    @classmethod
    def record(cls, session: "AnySession", session_id: str | None, step: str, **meta) -> "Event":
        ev = cls(session_id=session_id, step=step, meta=json.dumps(meta, ensure_ascii=False))
        session.add(ev)
        return ev


from typing import Protocol


class AnySession(Protocol):
    """Anything with .add() — SQLAlchemy Session satisfies this structurally."""

    def add(self, obj: object) -> None: ...
