"""FastAPI application: catalog, checkup, health map, PDF pipeline, bookings, clinic metrics."""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from . import __version__
from .config import get_settings
from .db import get_db, init_db, session_scope
from .engine import (
    Catalog,
    STOP_MESSAGE,
    load_catalog,
    compute_checkup,
    package_price,
    red_flags_in,
)
from .models import (
    Booking,
    Checkup,
    Event,
    Patient,
    Result,
    ResultConfirmation,
    ResultSource,
    SourceFile,
    Status,
)
from .pipeline import PipelineScanError, run_pipeline, validate_row
from .seed import ASEL_PHONE, seed_demo
from .schemas import (
    BookingOut,
    BookingRequest,
    CatalogOut,
    CheckupOut,
    CheckupRequest,
    EventIn,
    GoalOut,
    HealthMapOut,
    LlmStatus,
    PackageSummary,
    PatientCreate,
    PatientOut,
    PdfConfirmOut,
    PdfConfirmRequest,
    PdfRowIn,
    PdfUploadOut,
    ResultOut,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
CATALOG = load_catalog()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_demo()
    get_settings().upload_dir and os.makedirs(get_settings().upload_dir, exist_ok=True)
    yield


app = FastAPI(title="Check-up Intelligence — PRIME", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _patient_or_404(db: Session, pid: str) -> Patient:
    p = db.get(Patient, pid)
    if p is None:
        raise HTTPException(404, "patient not found")
    return p


def _results_like(p: Patient):
    from .engine import PatientResultLike
    return [
        PatientResultLike(
            indicator_code=r.indicator_code, status=r.status.value if r.status else None,
            valid_until=r.valid_until, confirmation=r.confirmation.value if r.confirmation else "confirmed",
            exam_date=r.exam_date, value_text=r.value_text,
        )
        for r in p.results
    ]


# ---------------- health / llm status ----------------

@app.get("/api/health")
def health():
    s = get_settings()
    return {
        "ok": True, "version": __version__,
        "llm_provider": s.llm_provider, "llm_model": s.llm_model,
    }


@app.get("/api/llm/status", response_model=LlmStatus)
def llm_status():
    s = get_settings()
    if s.llm_provider == "mock":
        return LlmStatus(
            provider="mock", model="mock-extractor", base_url="—",
            can_parse_pdf=True,
            note=("Офлайн-демо: текстовые PDF разбираются детерминированным экстрактором "
                  "по словарю показателей. Для боевого разбора поставьте LLM_PROVIDER=openai "
                  "(Qwen 3.8-Max в облаке или vLLM с открытыми весами)."),
        )
    return LlmStatus(
        provider=s.llm_provider, model=s.llm_model, base_url=s.llm_base_url,
        can_parse_pdf=bool(s.llm_api_key),
        note=("OpenAI-совместимый endpoint. Сканы: для мультимодального Qwen-Max используйте "
              "только обезличенные файлы."),
    )


# ---------------- catalog & checkup ----------------

@app.get("/api/catalog", response_model=CatalogOut)
def catalog():
    goals = [GoalOut(**g) for g in CATALOG.goals.values()]
    pkgs = []
    for key, pkg in sorted(CATALOG.packages.items()):
        price = package_price(pkg, CATALOG.tests)
        items = [i for i in pkg.items if i.test_code in CATALOG.tests]
        dur = sum(CATALOG.tests[i.test_code].duration_min for i in items) + 15
        pkgs.append(PackageSummary(
            code=pkg.code, goal_code=pkg.goal_code, level=pkg.level,
            name=pkg.name, price_kzt=price, items_count=len(items), duration_min=dur,
        ))
    return CatalogOut(goals=goals, packages=pkgs)


@app.post("/api/checkup", response_model=CheckupOut)
def checkup(req: CheckupRequest, db: Session = Depends(get_db)):
    if req.goal_code not in CATALOG.goals:
        raise HTTPException(400, f"unknown goal: {req.goal_code}")

    results = None
    patient = None
    if req.patient_id:
        patient = _patient_or_404(db, req.patient_id)
        results = _results_like(patient)

    try:
        plan = compute_checkup(CATALOG, req.goal_code, req.level, req.sex, req.age, results)
    except KeyError as e:
        raise HTTPException(400, str(e)) from e

    # constructor: user-driven include/exclude (on top of the rule engine's decisions)
    by_code = {i["test_code"]: i for i in plan["items"]}
    extra_price = 0.0
    removed_price = 0.0
    for code in req.exclude:
        it = by_code.get(code)
        if it and it["include"]:
            it["include"] = False
            it["skipped"] = True
            it["skip_reason"] = "убрано в конструкторе"
            removed_price += it["price_kzt"]
    for code in req.include:
        if code in by_code:
            by_code[code]["include"] = True
            by_code[code]["skipped"] = False
            continue
        test = CATALOG.tests.get(code)
        if test is None:
            continue
        plan["items"].append({
            "test_code": code, "name": test.name, "label": "optional",
            "price_kzt": test.price_kzt, "include": True, "skipped": False,
            "skip_reason": None, "note": "добавлено вручную", "station": test.station,
            "prep": test.prep or None, "duration_min": test.duration_min,
        })
        extra_price += test.price_kzt

    final_price = plan["personal_price_kzt"] - removed_price + extra_price
    plan["personal_price_kzt"] = max(final_price, 0)

    red_flags = red_flags_in(req.complaints or "")
    plan["red_flags"] = red_flags
    plan["stop_message"] = STOP_MESSAGE if red_flags else None
    plan["session_id"] = req.session_id

    # persist the checkup for the funnel + booking link
    cu = Checkup(
        patient_id=patient.id if patient else None,
        session_id=req.session_id,
        goal_code=req.goal_code, level=req.level,
        package_name=plan["package_name"],
        package_price=plan["package_price_kzt"],
        personal_price=plan["personal_price_kzt"],
        dedup_saved=plan["dedup_saved_kzt"],
        total_duration_min=plan["total_duration_min"],
        red_flags=json.dumps(red_flags, ensure_ascii=False) or None,
        snapshot=json.dumps(plan, ensure_ascii=False),
    )
    db.add(cu)
    Event.record(db, req.session_id, "checkup", goal=req.goal_code, level=req.level,
                 price=plan["personal_price_kzt"], dedup=plan["dedup_saved_kzt"])
    db.commit()
    plan["checkup_id"] = cu.id
    return CheckupOut(**{k: v for k, v in plan.items() if k in CheckupOut.model_fields})


# ---------------- events ----------------

@app.post("/api/events", status_code=202)
def track(ev: EventIn, db: Session = Depends(get_db)):
    e = Event(session_id=ev.session_id, step=ev.step,
              meta=json.dumps(ev.meta or {}, ensure_ascii=False))
    db.add(e)
    db.commit()
    return {"ok": True}


# ---------------- patients & health map ----------------

@app.post("/api/patients", response_model=PatientOut, status_code=201)
def create_patient(body: PatientCreate, db: Session = Depends(get_db)):
    if body.phone:
        existing = db.scalar(select(Patient).where(Patient.phone == body.phone))
        if existing:
            if body.consent_health:
                existing.consent_health = True
                existing.consent_at = dt.datetime.now(dt.timezone.utc)
            return existing
    p = Patient(
        first_name=body.first_name, last_name=body.last_name, sex=body.sex,
        birth_year=body.birth_year, phone=body.phone,
        consent_health=body.consent_health,
        consent_at=dt.datetime.now(dt.timezone.utc) if body.consent_health else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@app.get("/api/patients/{pid}/healthmap", response_model=HealthMapOut)
def healthmap(pid: str, db: Session = Depends(get_db)):
    p = _patient_or_404(db, pid)
    confirmed = [r for r in p.results
                 if r.confirmation in (ResultConfirmation.confirmed, ResultConfirmation.corrected)]
    results = sorted(confirmed, key=lambda r: r.exam_date or dt.date.min, reverse=True)

    today = dt.date.today()
    repeat_soon = []
    for r in results:
        if r.valid_until and 0 <= (r.valid_until - today).days <= 30:
            repeat_soon.append({
                "indicator_code": r.indicator_code,
                "valid_until": r.valid_until.isoformat(),
                "days_left": (r.valid_until - today).days,
            })

    trends = []
    by_code: dict[str, list[Result]] = {}
    for r in sorted(results, key=lambda r: r.exam_date or dt.date.min):
        by_code.setdefault(r.indicator_code, []).append(r)
    for code, rows in by_code.items():
        if len(rows) < 2:
            continue
        last3 = rows[-3:]
        trends.append({
            "indicator_code": code,
            "points": [
                {"date": r.exam_date.isoformat() if r.exam_date else None,
                 "value_text": r.value_text, "status": r.status.value if r.status else None}
                for r in last3
            ],
        })

    return HealthMapOut(
        patient=PatientOut.model_validate(p),
        results=[ResultOut.model_validate(r) for r in results],
        repeat_soon=repeat_soon,
        trends=trends,
    )


@app.post("/api/patients/{pid}/results", status_code=201)
def add_result_manual(pid: str, body: PdfRowIn, db: Session = Depends(get_db)):
    """Admin manual entry (MVP path for scans/failed OCR)."""
    p = _patient_or_404(db, pid)
    v = validate_row(body.model_dump(exclude_none=True), dt.date.today())
    if v.code is None:
        raise HTTPException(400, f"неизвестный показатель: {v.name!r}. Допустимые коды: "
                                 f"{', '.join(sorted(CATALOG.tests))}")
    test = CATALOG.tests[v.code]
    exam = v.date or dt.date.today().isoformat()
    import datetime as _dt
    d = _dt.date.fromisoformat(exam)
    import calendar
    y = d.year + (d.month - 1 + test.validity_months) // 12
    m = (d.month - 1 + test.validity_months) % 12 + 1
    vu = _dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
    r = Result(
        patient_id=pid, indicator_code=v.code, value_text=body.value,
        value_num=v.value_num, unit=body.unit or v.std_unit,
        reference=body.reference or test.name, exam_date=d,
        status=Status(v.status) if v.status else Status.ok, valid_until=vu,
        source=ResultSource.manual, confirmation=ResultConfirmation.confirmed,
    )
    db.add(r)
    db.commit()
    return ResultOut.model_validate(r)


# ---------------- PDF pipeline ----------------

@app.post("/api/pdf", response_model=PdfUploadOut)
async def pdf_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    s = get_settings()
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "ожидается PDF-файл")
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"файл больше {s.max_upload_mb} МБ")
    if data[:5] != b"%PDF-":
        raise HTTPException(400, "это не PDF")

    os.makedirs(s.upload_dir, exist_ok=True)
    fid = uuid.uuid4().hex
    path = os.path.join(s.upload_dir, fid + ".pdf")
    with open(path, "wb") as f:
        f.write(data)

    sf = SourceFile(
        filename=file.filename or "upload.pdf", path=path, size=len(data),
        llm_provider=s.llm_provider, llm_model=s.llm_model,
    )
    db.add(sf)
    db.commit()

    today = dt.date.today()
    try:
        pr = run_pipeline(path, today, s.min_text_chars)
    except PipelineScanError as e:
        sf.kind = "scan"
        sf.page_count = e.pages
        sf.pipeline_ms = None
        Event.record(db, None, "pdf_scan_blocked")
        db.commit()
        raise HTTPException(422, detail={
            "error": str(e), "file_id": sf.id, "kind": "scan",
        })

    sf.page_count = 0
    sf.kind = pr.kind
    sf.text_chars = pr.text_chars
    sf.pipeline_ms = pr.ms
    db.commit()

    rows_out = []
    for row in pr.rows:
        r = Result(
            patient_id=None,
            indicator_code=row.code or row.name[:40],
            value_text=row.value, value_num=row.value_num,
            unit=row.std_unit or row.unit, reference=row.reference,
            exam_date=dt.date.fromisoformat(row.date) if row.date else None,
            status=Status(row.status) if row.status else None,
            valid_until=dt.date.fromisoformat(row.valid_until) if row.valid_until else None,
            source=ResultSource.pdf, confirmation=ResultConfirmation.pending,
            source_file_id=sf.id, flag="; ".join(row.flags) or None,
        )
        db.add(r)
        rows_out.append(row.to_dict())
    Event.record(db, None, "pdf_extracted", ok=len(pr.confirmed_rows),
                 flagged=len(pr.rows) - len(pr.confirmed_rows), ms=pr.ms)
    db.commit()
    return PdfUploadOut(
        file_id=sf.id, kind=pr.kind, report_date=pr.report_date,
        provider=pr.provider, model=pr.model, pipeline_ms=pr.ms,
        rows=rows_out, ok_count=len(pr.confirmed_rows),
        flagged_count=len(pr.rows) - len(pr.confirmed_rows),
    )


@app.post("/api/pdf/{file_id}/confirm", response_model=PdfConfirmOut)
def pdf_confirm(file_id: str, body: PdfConfirmRequest, db: Session = Depends(get_db)):
    p = _patient_or_404(db, body.patient_id)
    sf = db.get(SourceFile, file_id)
    if sf is None:
        raise HTTPException(404, "file not found")
    pending = db.scalars(select(Result).where(
        Result.source_file_id == file_id,
        Result.confirmation == ResultConfirmation.pending,
    )).all()
    if not pending:
        raise HTTPException(409, "все значения уже подтверждены")

    by_name = {r.indicator_code: r for r in pending}
    rows_by_idx = list(pending)
    saved, skipped = 0, 0
    flagged = []
    for i, row in enumerate(body.rows):
        if row.remove or i >= len(rows_by_idx):
            continue
        r = by_name.get(row.name) or next(
            (x for x in rows_by_idx if x.indicator_code == row.name.lower()), None)
        if r is None:
            flagged.append({"row": row.name, "reason": "строка не найдена"})
            continue
        if r.flag:
            # was suspicious in the pipeline — human decision required:
            # only accept if the user explicitly kept a value (no change + ok)
            if not row.value and not row.unit:
                r.confirmation = ResultConfirmation.extracted
                flagged.append({"row": row.name, "reason": r.flag, "kept": False})
                continue
        r.confirmation = ResultConfirmation.corrected if (r.value_text != row.value or
                                                         r.unit != (row.unit or r.unit)) \
            else ResultConfirmation.confirmed
        r.patient_id = p.id
        if row.value is not None:
            r.value_text = row.value
        if row.unit:
            r.unit = row.unit
        if row.reference:
            r.reference = row.reference
        if row.date:
            try:
                r.exam_date = dt.date.fromisoformat(row.date)
            except ValueError:
                pass
        saved += 1
    # remove rows
    for row in body.rows:
        if row.remove:
            for r in rows_by_idx:
                if r.indicator_code == row.name.lower() or r.indicator_code == row.name:
                    db.delete(r)
                    skipped += 1
    Event.record(db, None, "pdf_confirmed", saved=saved, removed=skipped)
    db.commit()
    codes = [c for c in by_name if c in CATALOG.tests]
    return PdfConfirmOut(saved=saved, skipped=skipped, flagged=flagged,
                         healthmap_saved=codes)


# ---------------- bookings ----------------

@app.post("/api/bookings", response_model=BookingOut, status_code=201)
def create_booking(body: BookingRequest, db: Session = Depends(get_db)):
    if not body.consent:
        raise HTTPException(400, "нужно согласие на обработку данных о здоровье")
    p = _patient_or_404(db, body.patient_id)
    if body.phone and not p.phone:
        p.phone = body.phone
    cu = body.checkup
    b = Booking(
        patient_id=p.id,
        visit_date=body.visit_date,
        status="pending",
        total_kzt=cu.get("personal_price_kzt", 0),
        dedup_saved_kzt=cu.get("dedup_saved_kzt", 0),
        channel=body.channel,
        consent_at=dt.datetime.now(dt.timezone.utc),
        meta=json.dumps(cu, ensure_ascii=False),
    )
    db.add(b)
    Event.record(db, cu.get("session_id"), "booked",
                 price=b.total_kzt, dedup=b.dedup_saved_kzt, date=body.visit_date.isoformat())
    db.commit()
    db.refresh(b)
    return BookingOut.model_validate(b)


# ---------------- clinic dashboard ----------------

@app.get("/api/clinic/metrics")
def clinic_metrics(db: Session = Depends(get_db)):
    steps = ["goal", "checkup", "pdf_extracted", "pdf_confirmed", "booked"]
    total = {}
    for st in steps:
        total[st] = db.scalar(select(func.count()).select_from(Event).where(Event.step == st)) or 0
    booked = db.scalar(select(func.count()).select_from(Booking)) or 0
    revenue = db.scalar(select(func.coalesce(func.sum(Booking.total_kzt), 0)).select_from(Booking)) or 0
    dedup_total = db.scalar(select(func.coalesce(func.sum(Booking.dedup_saved_kzt), 0)).select_from(Booking)) or 0
    level_dist = {}
    for cu in db.scalars(select(Checkup.level)).all():
        level_dist[cu] = level_dist.get(cu, 0) + 1
    return {
        "events": total,
        "bookings": booked,
        "revenue_kzt": float(revenue),
        "dedup_saved_kzt": float(dedup_total),
        "level_distribution": level_dist,
        "conversion_booked_pct": round(100 * booked / total["checkup"], 1) if total["checkup"] else 0,
    }


@app.get("/api/clinic/bookings")
def clinic_bookings(db: Session = Depends(get_db), limit: int = 50):
    rows = db.scalars(
        select(Booking).order_by(desc(Booking.created_at)).limit(limit)
    ).all()
    out = []
    for b in rows:
        p = db.get(Patient, b.patient_id)
        out.append({
            "id": b.id, "date": b.visit_date.isoformat(), "status": b.status,
            "total_kzt": b.total_kzt, "dedup_saved_kzt": b.dedup_saved_kzt,
            "channel": b.channel,
            "patient": f"{p.first_name} {p.last_name or ''}".strip() if p else "?",
            "phone": p.phone if p else None,
            "created_at": b.created_at.isoformat(),
        })
    return {"bookings": out}


@app.get("/api/demo/asel")
def demo_asel(db: Session = Depends(get_db)):
    p = db.scalar(select(Patient).where(Patient.phone == ASEL_PHONE))
    if p is None:
        seed_demo()
        p = db.scalar(select(Patient).where(Patient.phone == ASEL_PHONE))
    if p is None:
        raise HTTPException(500, "demo seed failed")
    return {"patient_id": p.id, "name": f"{p.first_name} {p.last_name}"}


# ---------------- frontend ----------------

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def main():
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
