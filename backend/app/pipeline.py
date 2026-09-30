"""PDF pipeline (plan §2): extract text -> LLM structures -> code validates -> human confirms.

Model extracts, code checks, human confirms. A recognition error must never
silently become a medical conclusion.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import pymupdf  # MuPDF

from . import indicators as ind
from .llm import LLMError, structure_report


@dataclass
class ExtractedRow:
    name: str
    value: str | None          # as in the report (string)
    unit: str | None
    reference: str | None
    date: str | None
    # validation output:
    code: str | None = None
    canonical_name: str | None = None
    value_num: float | None = None
    std_unit: str | None = None
    value_std: str | None = None   # normalised value for display (after unit conversion)
    status: str | None = None
    valid_until: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.flags

    def to_dict(self) -> dict:
        return {
            "name": self.name, "value": self.value, "unit": self.unit,
            "reference": self.reference, "date": self.date,
            "code": self.code, "canonical_name": self.canonical_name,
            "value_num": self.value_num, "std_unit": self.std_unit,
            "value_std": self.value_std,
            "status": self.status, "valid_until": self.valid_until,
            "flags": self.flags, "ok": self.ok,
        }


_DATE_FMTS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d/%m/%y")


def parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in _DATE_FMTS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def extract_text(path: str) -> tuple[str, int]:
    """Pass 1: text layer without AI — fast, cheap, data stays local."""
    doc = pymupdf.open(path)
    pages = doc.page_count
    parts = []
    try:
        for page in doc:
            parts.append(page.get_text("text"))
    finally:
        doc.close()
    text = "\n".join(p for p in parts if p.strip())
    return text, pages


def validate_row(row: dict, today: dt.date) -> ExtractedRow:
    """Code checks every model output against the dictionary (plan §2.5)."""
    out = ExtractedRow(
        name=str(row.get("name", "")).strip(),
        value=None if row.get("value") is None else str(row.get("value")).strip(),
        unit=(str(row.get("unit")).strip() if row.get("unit") else None),
        reference=(str(row.get("reference")).strip() if row.get("reference") else None),
        date=(str(row.get("date")).strip() if row.get("date") else None),
    )
    if not out.name:
        out.flags.append("пустое название")
        return out

    known = ind.get(out.name)
    if known is None:
        out.flags.append("неизвестный показатель (не в словаре)")
        return out
    out.code = known.code
    out.canonical_name = known.name

    # date checks
    d = parse_date(out.date)
    if out.date and d is None:
        out.flags.append(f"не распознана дата: {out.date!r}")
    if d is not None and d > today:
        out.flags.append(f"дата в будущем: {d.isoformat()}")
    if out.code and d is not None:
        y = today.year + (today.month - 1 + known.validity_months) // 12
        m = (today.month - 1 + known.validity_months) % 12 + 1
        import calendar
        day = min(d.day, calendar.monthrange(y, m)[1])
        out.valid_until = dt.date(y, m, day).isoformat()

    # numeric checks
    if out.value in (None, ""):
        out.flags.append("нет значения")
        return out
    num = _try_num(out.value)
    if known.ref_low is not None or known.ref_high is not None:
        # quantitative indicator: value must be numeric (or a known qualitative for rh)
        if out.code == "rh":
            v = out.value.lower()
            if v in ("+", "положительный", "positive"):
                num, out.std_unit = 1.0, known.unit
            elif v in ("−", "-", "отрицательный", "negative"):
                num, out.std_unit = -1.0, known.unit
            else:
                out.flags.append("резус: ожидалось + / −")
                return out
        elif out.code == "ab0":
            m = re.search(r"([1-4])", out.value)
            if m:
                num, out.std_unit = float(m.group(1)), known.unit
            else:
                out.flags.append("группа крови: ожидалось I–IV")
                return out
        else:
            if num is None:
                out.flags.append(f"ожидалось число, получено: {out.value!r}")
                return out
            if known.unit_aliases and out.unit:
                conv = ind.to_standard_unit(num, out.unit, known)
                if conv is None:
                    out.flags.append(f"неизвестная единица: {out.unit!r}")
                    return out
                num, out.std_unit = conv
            else:
                out.std_unit = known.unit
            out.value_num = num
            out.value_std = f"{num:g}"
            if not (known.plausible_min <= num <= known.plausible_max):
                out.flags.append(
                    f"значение {num} вне правдоподобного диапазона "
                    f"[{known.plausible_min}, {known.plausible_max}]"
                )
            # status vs reference
            if known.ref_low is not None and num < known.ref_low:
                out.status = "borderline" if num >= known.plausible_min and _near(num, known.ref_low) else "abnormal"
            elif known.ref_high is not None and num > known.ref_high:
                out.status = "borderline" if _near(num, known.ref_high) else "abnormal"
            else:
                out.status = "ok"
    else:
        # qualitative (consultation/imaging) — accept text, mark ok
        out.value_num = None
        out.std_unit = known.unit
        out.status = "ok"
    return out


def _near(x: float, edge: float, tol: float = 0.15) -> bool:
    """Within 15% of the reference edge -> borderline, not abnormal."""
    if edge == 0:
        return True
    return abs(x - edge) / max(abs(edge), 1e-9) <= tol


def _try_num(s: str) -> float | None:
    try:
        return float(s.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


@dataclass
class PipelineResult:
    rows: list[ExtractedRow]
    report_date: str | None
    provider: str
    model: str
    text_chars: int
    kind: str  # text | scan
    llm_raw: str
    ms: int

    @property
    def confirmed_rows(self) -> list[ExtractedRow]:
        return [r for r in self.rows if r.ok]

    def to_dict(self) -> dict:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "report_date": self.report_date,
            "provider": self.provider,
            "model": self.model,
            "text_chars": self.text_chars,
            "kind": self.kind,
            "ok_count": len(self.confirmed_rows),
            "flagged_count": len(self.rows) - len(self.confirmed_rows),
        }


def run_pipeline(
    path: str,
    today: dt.date,
    min_text_chars: int = 60,
    llm_callable=None,
) -> PipelineResult:
    """Full pipeline. `llm_callable` injectable for tests (fn(text)->LLMResult)."""
    import time

    t0 = time.monotonic()
    text, pages = extract_text(path)
    kind = "text" if len(text.strip()) >= min_text_chars else "scan"
    if kind == "scan":
        # MVP: no local OCR installed -> flag for manual entry (plan §9).
        # With Qwen-Max cloud (de-identified files) or a PaddleOCR sidecar this
        # stage would render pages to images and send them to the model.
        raise PipelineScanError(
            "В PDF нет текстового слоя — это скан. OCR-этап: подключите mультимодальную "
            "модель (Qwen-Max, обезличенные файлы) или PaddleOCR. Пока — введите значения вручную.",
            pages=pages,
        )

    llm_fn = llm_callable or structure_report
    try:
        res = llm_fn(text)
    except LLMError as e:
        # fallback to the deterministic extractor so the demo never hard-fails
        from .llm import mock_structuring
        res = mock_structuring(text)
        provider_note = f"fallback: {e}"
    else:
        provider_note = ""

    rows = [validate_row(r, today) for r in res.indicators]
    # de-duplicate rows by code (keep first)
    seen: set[str] = set()
    uniq: list[ExtractedRow] = []
    for r in rows:
        key = r.code or r.name.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    ms = int((time.monotonic() - t0) * 1000)
    return PipelineResult(
        rows=uniq,
        report_date=res.report_date,
        provider=f"{res.provider}" + (f" ({provider_note})" if provider_note else ""),
        model=res.model,
        text_chars=len(text),
        kind=kind,
        llm_raw=res.raw,
        ms=ms,
    )


class PipelineScanError(Exception):
    def __init__(self, msg: str, pages: int = 0):
        super().__init__(msg)
        self.pages = pages
