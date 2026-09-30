"""Rule engine: package composition, deduplication, personal price, route, red flags.

Pure functions over plain data — the LLM never decides here. Rules live in CSV
(data/tests.csv, data/packages.csv, data/goals.csv): doctors edit the files,
redeploy (or reload in admin) — no code change needed.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# biochem panel covers these single indicators (dedup: skip only if ALL are fresh-ok)
PANEL_COVERS: dict[str, list[str]] = {
    "biochem": ["glu", "chol", "alt", "ast", "crea"],
}

RED_FLAG_PATTERNS: list[tuple[str, str]] = [
    (r"кров\w* (в|на) (кал|моч|рвот)", "кровь в выделениях"),
    (r"кровотечени", "кровотечение"),
    (r"(боль|болят|болит)\w*.{0,40}(день|сутк|недел)", "боль, длящаяся более 1 дня"),
    (r"температур\w*\s+(\d{2}[.,]\d?|высока|субфебрил|свыше|до \d)", "повышенная температура"),
    (r"потеря(ли)? (веса|массы)", "необъяснимая потеря веса"),
    (r"онко|опухол\w*|раковин\w*", "упоминание онкологии"),
    (r"судорог|эпилепс\w*", "судороги"),
    (r"(потеря|потерял\w*|отключил\w*) сознани", "потеря сознания"),
    (r"одышк\w*|не (могу|хватает) дыхания", "одышка / затруднённое дыхание"),
    (r"боль в груди|грудной клетк\w* (болит|боль)", "боль в груди"),
    (r"давит (на) (голову|висок)\w* (сильн|постоянн)", "сильная/постоянная головная боль"),
]

STOP_MESSAGE = (
    "По описанию вам нужен врач очно, а не чекап. Позвоните в регистратуру PRIME: "
    "+7 7172 555 555 — примут на приём в день обращения. Чекап подождёт."
)


@dataclass(frozen=True)
class Test:
    code: str
    name: str
    category: str
    price_kzt: float
    validity_months: int
    prep: str
    station: str
    duration_min: int
    is_consult: bool


@dataclass(frozen=True)
class PackageItem:
    test_code: str
    label: str  # required | recommended | optional


@dataclass(frozen=True)
class Package:
    code: str
    goal_code: str
    level: str  # min | rec | max
    name: str
    package_price_kzt: float | None  # None -> sum of items
    items: list[PackageItem] = field(default_factory=list)


@dataclass
class Catalog:
    tests: dict[str, Test]
    goals: dict[str, dict]
    packages: dict[str, Package]


def load_catalog(data_dir: Path | None = None) -> Catalog:
    d = data_dir or DATA_DIR
    tests: dict[str, Test] = {}
    with open(d / "tests.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tests[row["code"]] = Test(
                code=row["code"],
                name=row["name"],
                category=row["category"],
                price_kzt=float(row["price_kzt"]),
                validity_months=int(row["validity_months"]),
                prep=(row["prep"] or "").strip(),
                station=row["station"],
                duration_min=int(row["duration_min"]),
                is_consult=row["is_consult"] == "1",
            )
    goals = {}
    with open(d / "goals.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            goals[row["code"]] = row
    packages: dict[str, Package] = {}
    with open(d / "packages.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["goal_code"], row["level"])
            price_s = (row["package_price_kzt"] or "").strip()
            pkg = packages.setdefault(key[0] + "|" + key[1], Package(
                code=row["code"], goal_code=row["goal_code"], level=row["level"],
                name=row["name"],
                package_price_kzt=float(price_s) if price_s else None,
            ))
            pkg.items.append(PackageItem(test_code=row["test_code"], label=row["label"]))
    return Catalog(tests=tests, goals=goals, packages=packages)


# ---------------- dedup ----------------

@dataclass
class DedupDecision:
    test_code: str
    include: bool
    skip: bool
    skip_reason: str | None
    note: str | None
    saved_kzt: float = 0.0


@dataclass
class PatientResultLike:
    """What the engine needs from a stored result (DB row or test stub)."""
    indicator_code: str
    status: str | None          # ok | borderline | abnormal
    valid_until: date | None
    confirmation: str = "confirmed"
    exam_date: date | None = None
    value_text: str | None = None


def _month_end(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # clamp day
    if m == 2:
        day = min(d.day, 28)
    else:
        day = min(d.day, 31)
    return date(y, m, day)


def dedup_item(
    item_test_code: str,
    test: Test,
    results: list[PatientResultLike],
    today: date,
) -> DedupDecision:
    """Apply the dedup rules from docs/PLAN.md §2.4 to one package item."""
    if test.is_consult:
        return DedupDecision(item_test_code, True, False, None, None)

    covers = PANEL_COVERS.get(item_test_code, [item_test_code])
    by_code: dict[str, PatientResultLike] = {}
    for r in results:
        if r.confirmation not in ("confirmed", "corrected"):
            continue  # only confirmed results form the health map
        if r.indicator_code in covers:
            cur = by_code.get(r.indicator_code)
            if cur is None or (r.exam_date or date.min) > (cur.exam_date or date.min):
                by_code[r.indicator_code] = r

    all_fresh_ok = True
    notes: list[str] = []
    for code in covers:
        r = by_code.get(code)
        if r is None:
            all_fresh_ok = False
            continue
        if r.status in ("abnormal", "borderline"):
            all_fresh_ok = False
            label = "повторить — ранее было отклонение" if r.status == "abnormal" \
                else "на границе нормы — рекомендуем контрольный замер"
            notes.append(label)
        elif r.valid_until is None or r.valid_until < today:
            all_fresh_ok = False
    if notes:
        return DedupDecision(item_test_code, True, False, None, " ".join(dict.fromkeys(notes)))
    if all_fresh_ok:
        return DedupDecision(
            item_test_code, False, True,
            "уже есть свежий результат", None, saved_kzt=test.price_kzt,
        )
    return DedupDecision(item_test_code, True, False, None, None)


# ---------------- composition ----------------

AGE40_PLUS_EXTRAS = ["hba1c", "ldl", "tg"]  # added to for_myself at 40+


def age_adjustments(goal_code: str, age: int | None) -> list[str]:
    if goal_code == "for_myself" and age is not None and age >= 40:
        return [c for c in AGE40_PLUS_EXTRAS]
    return []


def package_price(pkg: Package, tests: dict[str, Test]) -> float:
    if pkg.package_price_kzt is not None:
        return pkg.package_price_kzt
    return sum(tests[i.test_code].price_kzt for i in pkg.items if i.test_code in tests)


def red_flags_in(text: str) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for pat, label in RED_FLAG_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(label)
    return hits


# ---------------- route ----------------

STATION_ORDER = {"забор крови": 0, "ЭКГ": 1, "рентген": 1, "лаб": 2, "УЗИ": 3, "врач": 4}
ROUTE_START = "08:30"


def _add_minutes(t: str, mins: int) -> str:
    h, m = map(int, t.split(":"))
    m += mins
    h += m // 60
    m %= 60
    return f"{h:02d}:{m:02d}"


def build_route(items: list[tuple[str, Test]]) -> list[dict]:
    """Ordered day route: fasting blood first, then ECG/X-ray, ultrasound, doctors."""
    ordered = sorted(
        items,
        key=lambda it: (STATION_ORDER.get(it[1].station, 9), it[1].duration_min),
    )
    t = ROUTE_START
    route = []
    for code, test in ordered:
        start = t
        t = _add_minutes(t, test.duration_min)
        route.append({
            "test_code": code, "name": test.name, "station": test.station,
            "start": start, "end": t, "duration_min": test.duration_min,
            "prep": test.prep or None,
        })
    return route


# ---------------- checkup (the orchestrating pure function) ----------------

def compute_checkup(
    catalog: Catalog,
    goal_code: str,
    level: str,
    sex: str,
    age: int | None,
    results: list[PatientResultLike] | None,
    today: date | None = None,
) -> dict:
    """Return the full checkup plan as a dict: package, decisions, prices, route.

    `results` may be None (new patient, scenario A) or the patient's confirmed
    health-map rows (scenario B — Asel).
    """
    today = today or date.today()
    key = f"{goal_code}|{level}"
    pkg = catalog.packages.get(key)
    if pkg is None:
        raise KeyError(f"package not found: {key}")
    results = results or []

    items = list(pkg.items)
    extras = age_adjustments(goal_code, age)
    for code in extras:
        if code in catalog.tests and all(i.test_code != code for i in items):
            items.append(PackageItem(code, "recommended"))

    decisions: list[DedupDecision] = []
    for it in items:
        test = catalog.tests.get(it.test_code)
        if test is None:
            continue
        d = dedup_item(it.test_code, test, results, today)
        d.test_code = it.test_code
        decisions.append(d)

    included = [d for d in decisions if d.include]
    skipped = [d for d in decisions if d.skip]
    package_total = package_price(pkg, catalog.tests)
    dedup_saved = sum(d.saved_kzt for d in skipped)
    personal = package_total - dedup_saved

    route_items = [(d.test_code, catalog.tests[d.test_code]) for d in included]
    route = build_route(route_items)
    total_min = sum(r["duration_min"] for r in route) + 15  # 15 min buffer between stations

    # red flags from abnormal/borderline results that the plan now repeats
    risk_notes = [d.note for d in decisions if d.note]
    repeat_soon = []
    for r in results:
        if r.valid_until and 0 <= (r.valid_until - today).days <= 30 and r.confirmation in ("confirmed", "corrected"):
            ind_name = r.indicator_code
            repeat_soon.append(f"{ind_name}: действует до {r.valid_until.isoformat()}")

    return {
        "goal_code": goal_code,
        "level": level,
        "package_code": pkg.code,
        "package_name": pkg.name,
        "package_price_kzt": package_total,
        "dedup_saved_kzt": dedup_saved,
        "personal_price_kzt": personal,
        "items": [
            {
                "test_code": d.test_code,
                "name": catalog.tests[d.test_code].name,
                "label": next(i.label for i in items if i.test_code == d.test_code),
                "price_kzt": catalog.tests[d.test_code].price_kzt,
                "include": d.include,
                "skipped": d.skip,
                "skip_reason": d.skip_reason,
                "note": d.note,
                "station": catalog.tests[d.test_code].station,
                "prep": catalog.tests[d.test_code].prep or None,
                "duration_min": catalog.tests[d.test_code].duration_min,
            }
            for d in decisions
        ],
        "route": route,
        "total_duration_min": total_min,
        "age_extras": extras,
        "risk_notes": risk_notes,
        "repeat_soon": repeat_soon,
    }
