"""Demo seed: Асель Каримова (plan §5). Idempotent — safe to call on every startup."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from .db import get_session
from .models import Patient, Result, ResultSource, ResultConfirmation, Status

ASEL_PHONE = "+77071112233"


def _month(year: int, month: int, day: int = 15) -> date:
    return date(year, month, day)


def seed_demo() -> dict:
    """Create Asel + Dansar with the history from docs/PLAN.md §5 (if absent)."""
    session = get_session()
    try:
        asel = session.scalar(select(Patient).where(Patient.phone == ASEL_PHONE))
        if asel is not None:
            return {"created": False, "patient_id": asel.id}

        dansar = Patient(
            first_name="Данияр", last_name="Каримов", sex="m",
            birth_year=1993, phone=ASEL_PHONE[:-1] + "4",
            consent_health=True,
        )
        asel = Patient(
            first_name="Асель", last_name="Каримова", sex="f",
            birth_year=1995, phone=ASEL_PHONE, family_id=None,
            consent_health=True,
        )
        session.add(dansar)
        session.add(asel)
        session.flush()
        dansar.family_id = asel.id  # same family (pair)

        def res(code, y, m, value_text, status, valid_until, value_num=None, unit=None, reference=None):
            return Result(
                patient_id=asel.id, indicator_code=code, value_text=value_text,
                value_num=value_num, unit=unit, reference=reference,
                exam_date=_month(y, m), status=status, valid_until=valid_until,
                source=ResultSource.clinic, confirmation=ResultConfirmation.confirmed,
            )

        today = date.today()
        # апр 2026: ферритин на нижней границе (borderline), D снижен (abnormal)
        session.add(res("ferr", 2026, 4, "13 нг/мл", Status.borderline, _month(2026, 10), 13.0, "нг/мл", "12–250"))
        session.add(res("vitd", 2026, 4, "41 нмоль/л", Status.abnormal, _month(2026, 10), 41.0, "нмоль/л", "50–250"))
        # авг 2026: ОАК, ТТГ, глюкоза — ок до ноя 2026
        session.add(res("oak", 2026, 8, "в норме", Status.ok, _month(2026, 11)))
        session.add(res("tsh", 2026, 8, "1.8 мМЕ/л", Status.ok, _month(2026, 11), 1.8, "мМЕ/л", "0.4–4.0"))
        session.add(res("glu", 2026, 8, "4.9 ммоль/л", Status.ok, _month(2026, 11), 4.9, "ммоль/л", "3.3–5.6"))
        # нояб 2025: гинеколог, цитология, УЗИ МТ — ок до нояб 2026
        session.add(res("gyn", 2025, 11, "без патологии", Status.ok, _month(2026, 11)))
        session.add(res("cyto", 2025, 11, "без атипии", Status.ok, _month(2026, 11)))
        session.add(res("us_mt", 2025, 11, "без патологии", Status.ok, _month(2026, 11)))
        # 40-летняя флюорография уже в этом году (демо)
        session.add(res("fluoro", today.year, max(1, today.month - 1), "без патологии", Status.ok,
                        _month(today.year + 1, max(1, today.month - 1))))
        session.commit()
        return {"created": True, "patient_id": asel.id, "partner_id": dansar.id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
