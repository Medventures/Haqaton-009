"""Indicator dictionary (словарь показателей).

This is the ONLY source of truth for known indicators, standard units,
reference ranges and plausibility bounds. The LLM may output any text;
the pipeline maps it here and flags everything it can't explain.

Reference ranges and validity months are DEMO values — PRIME doctors must
approve them (docs/PLAN.md §11). They live in data, not in logic.

Units are normalised to a standard unit per indicator; the converter
handles common lab variants (µg/L == ng/mL, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Indicator:
    code: str
    name: str                      # canonical Russian name
    aliases: tuple[str, ...]       # lowercased, for name matching
    unit: str                      # standard unit
    unit_aliases: tuple[str, ...]  # acceptable unit spellings (lowercased)
    ref_low: float | None
    ref_high: float | None
    ref_text: str                  # human-readable reference for the UI
    plausible_min: float           # outside this -> flagged as implausible
    plausible_max: float
    validity_months: int           # how long a result stays valid (doctor-approved)
    is_analysis: bool = True       # False = consultation/service, never deduped


CATALOG: dict[str, Indicator] = {}


def _add(ind: Indicator) -> None:
    CATALOG[ind.code] = ind
    for alias in (ind.name.lower(),) + ind.aliases:
        ALIASES[alias] = ind.code


ALIASES: dict[str, str] = {}


# ---------------- blood (hematology / biochemistry) ----------------
_add(Indicator(
    code="oak", name="Общий анализ крови (ОАК)",
    aliases=("оак", "общий анализ крови", "complete blood count", "cbc", "полный анализ крови"),
    unit="—", unit_aliases=("—", "-", "ед"),
    ref_low=None, ref_high=None, ref_text="в пределах референса лаборатории",
    plausible_min=0, plausible_max=1, validity_months=3, is_analysis=True,
))
_add(Indicator(
    code="wbc", name="Лейкоциты",
    aliases=("лейкоциты", "wbc", "leukocytes", " лейкоциты "),
    unit="10⁹/л", unit_aliases=("10^9/л", "10^9/l", "e9/l", "10*9/л", "g/l", "109/л"),
    ref_low=4.0, ref_high=9.0, ref_text="4.0–9.0",
    plausible_min=0.5, plausible_max=100, validity_months=3,
))
_add(Indicator(
    code="hb", name="Гемоглобин",
    aliases=("гемоглобин", "hemoglobin", "hb"),
    unit="г/л", unit_aliases=("г/л", "g/l"),  # г/дл & g/dl are conversions, not aliases
    ref_low=120, ref_high=160, ref_text="120–160 (Ж) / 130–170 (М)",
    plausible_min=30, plausible_max=300, validity_months=3,
))
_add(Indicator(
    code="pl", name="Тромбоциты",
    aliases=("тромбоциты", "thrombocytes", "plt"),
    unit="10⁹/л", unit_aliases=("10^9/л", "e9/l", "109/л"),
    ref_low=180, ref_high=320, ref_text="180–320",
    plausible_min=20, plausible_max=1500, validity_months=3,
))
_add(Indicator(
    code="glu", name="Глюкоза (натощак)",
    aliases=("глюкоза", "glucose", "глюкоза крови", "glc"),
    unit="ммоль/л", unit_aliases=("ммоль/л", "mmol/l", "ммоль/л"),
    ref_low=3.3, ref_high=5.6, ref_text="3.3–5.6",
    plausible_min=0.5, plausible_max=40, validity_months=3,
))
_add(Indicator(
    code="hba1c", name="Гликированный гемоглобин (HbA1c)",
    aliases=("hba1c", "гликированный гемоглобин", "glycated hemoglobin", "hba1с"),
    unit="%", unit_aliases=("%", "проценты"),
    ref_low=4.0, ref_high=6.0, ref_text="4.0–6.0",
    plausible_min=3.0, plausible_max=25, validity_months=6,
))
_add(Indicator(
    code="chol", name="Холестерин (общий)",
    aliases=("холестерин", "cholesterol", "общий холестерин", "chol"),
    unit="ммоль/л", unit_aliases=("ммоль/л", "mmol/l"),
    ref_low=None, ref_high=5.2, ref_text="< 5.2",
    plausible_min=1.0, plausible_max=25, validity_months=12,
))
_add(Indicator(
    code="ldl", name="ЛПНП (холестерин «плохой»)",
    aliases=("лпнп", "ldl", "липопротеины низкой плотности", "lpln"),
    unit="ммоль/л", unit_aliases=("ммоль/л", "mmol/l"),
    ref_low=None, ref_high=3.5, ref_text="< 3.5 (базовый риск)",
    plausible_min=0.5, plausible_max=15, validity_months=12,
))
_add(Indicator(
    code="tg", name="Триглицериды",
    aliases=("триглицериды", "triglycerides", "tg", "trig"),
    unit="ммоль/л", unit_aliases=("ммоль/л", "mmol/l"),
    ref_low=0.4, ref_high=1.7, ref_text="0.4–1.7",
    plausible_min=0.1, plausible_max=20, validity_months=12,
))
_add(Indicator(
    code="alt", name="АЛТ (аланинаминотрансфераза)",
    aliases=("алт", "alt", "alanine aminotransferase", "alaninaminotransferase"),
    unit="Ед/л", unit_aliases=("ед/л", "u/l", "ед/л"),
    ref_low=5, ref_high=41, ref_text="5–41 (Ж) / 5–49 (М)",
    plausible_min=1, plausible_max=2000, validity_months=12,
))
_add(Indicator(
    code="ast", name="АСТ (аспартатаминотрансфераза)",
    aliases=("аст", "ast", "aspartate aminotransferase", "aspat"),
    unit="Ед/л", unit_aliases=("ед/л", "u/l"),
    ref_low=5, ref_high=35, ref_text="5–35 (Ж) / 5–41 (М)",
    plausible_min=1, plausible_max=2000, validity_months=12,
))
_add(Indicator(
    code="crea", name="Креатинин",
    aliases=("креатинин", "creatinine", "crea"),
    unit="мкмоль/л", unit_aliases=("мкмоль/л", "umol/l", "umol/l", "мкмоль/л"),
    ref_low=44, ref_high=110, ref_text="44–110 (Ж) / 62–132 (М)",
    plausible_min=10, plausible_max=2000, validity_months=12,
))
_add(Indicator(
    code="uric", name="Мочевая кислота",
    aliases=("мочевая кислота", "uric acid", "uric"),
    unit="мкмоль/л", unit_aliases=("мкмоль/л", "umol/l", "мкмоль/л"),
    ref_low=150, ref_high=400, ref_text="150–400 (Ж) / 210–430 (М)",
    plausible_min=50, plausible_max=1500, validity_months=12,
))
_add(Indicator(
    code="tsh", name="ТТГ (тиреотропный гормон)",
    aliases=("ттг", "tsh", "тиреотропный гормон", "tirostimulating", "тиреостимулирующий"),
    unit="мМЕ/л", unit_aliases=("мме/л", "mu/l", "muiu/ml", "me/l"),
    ref_low=0.4, ref_high=4.0, ref_text="0.4–4.0",
    plausible_min=0.01, plausible_max=100, validity_months=12,
))
_add(Indicator(
    code="t4", name="Т4 свободный",
    aliases=("т4 свободный", "t4 свободный", "ft4", "free t4", "t4s"),
    unit="пмоль/л", unit_aliases=("пмоль/л", "pmol/l", "pg/ml"),
    ref_low=12, ref_high=22, ref_text="12–22",
    plausible_min=2, plausible_max=100, validity_months=12,
))
_add(Indicator(
    code="ferr", name="Ферритин",
    aliases=("ферритин", "ferritin"),
    unit="нг/мл", unit_aliases=("нг/мл", "ng/ml", "мкг/л", "ug/l", "mcg/l"),
    ref_low=12, ref_high=250, ref_text="12–250 (Ж) / 25–400 (М)",
    plausible_min=1, plausible_max=3000, validity_months=6,
))
_add(Indicator(
    code="vitd", name="Витамин D (25-OH)",
    aliases=("витамин d", "витамин d3", "vitamin d", "vitamin d3", "25-oh", "25 oh витамин d",
            "25-(oh) vitamin d", "витамин d 25-oh", "d3", "тахокальциферол"),
    unit="нмоль/л", unit_aliases=("нмоль/л", "nmol/l"),  # нг/мл & ng/dl are conversions, not aliases
    ref_low=50, ref_high=250, ref_text="50–250 (дефицит < 50)",
    plausible_min=5, plausible_max=600, validity_months=6,
))
_add(Indicator(
    code="fe", name="Железо сывороточное",
    aliases=("железо", "железо сывороточное", "serum iron", "fe"),
    unit="мкмоль/л", unit_aliases=("мкмоль/л", "umol/l", "мкг/дл", "ug/dl"),
    ref_low=11, ref_high=30, ref_text="11–30 (Ж) / 12–30 (М)",
    plausible_min=1, plausible_max=100, validity_months=6,
))
_add(Indicator(
    code="crp", name="С-реактивный белок (СРБ)",
    aliases=("с-реактивный белок", "срб", "crp", "c-реактивный", "c reactive protein"),
    unit="мг/л", unit_aliases=("мг/л", "mg/l", "mg/l"),
    ref_low=0, ref_high=5, ref_text="< 5",
    plausible_min=0, plausible_max=500, validity_months=3,
))

# ---------------- gynecology / pregnancy / infections ----------------
_add(Indicator(
    code="cyto", name="Цитология шейки матки",
    aliases=("цитология", "цитологическое исследование", "pap test", "мазок на цитологию",
             "пап-тест", "oncocytology"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="без атипичных клеток",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="us_mt", name="УЗИ органов малого таза",
    aliases=("узи малого таза", "узи мт", "pelvic ultrasound", "узи мт"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="без патологии",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="gyn", name="Консультация гинеколога",
    aliases=("гинеколог", "консультация гинеколога", "gynecologist", "приём гинеколога"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="услуга",
    plausible_min=0, plausible_max=1, validity_months=12, is_analysis=False,
))
_add(Indicator(
    code="ab0", name="АБ0 (группа крови)",
    aliases=("группа крови", "ab0", "abo", "або", "группа крови по системе abo"),
    unit="группа", unit_aliases=("группа", "—", "-"),
    ref_low=None, ref_high=None, ref_text="I–IV",
    plausible_min=1, plausible_max=4, validity_months=120,
))
_add(Indicator(
    code="rh", name="Резус-фактор",
    aliases=("резус", "резус-фактор", "rh", "rh factor"),
    unit="+", unit_aliases=("+", "отрицательный", "положительный"),
    ref_low=None, ref_high=None, ref_text="+ / −",
    plausible_min=-1, plausible_max=1, validity_months=120,
))
_add(Indicator(
    code="torch", name="TORCH-инфекции (IgG)",
    aliases=("torch", "торч", "торч-инфекции", "toxo, rubella, cmv, hsv"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="иммунитет / нет",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="infect", name="Инфекции (по назначению: ВПЧ, ХЛМ и др.)",
    aliases=("инфекции", "хлм", "впч", "хламидии", "ureaplasma", "гинекологическая панель"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="отрицательно",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="consult_preg", name="Консультация по итогам (планирование)",
    aliases=("консультация по итогам", "итоговая консультация", "декодирование результатов"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="услуга",
    plausible_min=0, plausible_max=1, validity_months=12, is_analysis=False,
))

# ---------------- urology / andrology (partner) ----------------
_add(Indicator(
    code="andro", name="Консультация андролога/уролога",
    aliases=("андролог", "уролог", "андролог/уролог", "andrologist"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="услуга",
    plausible_min=0, plausible_max=1, validity_months=12, is_analysis=False,
))
_add(Indicator(
    code="sperm", name="Спермограмма",
    aliases=("спермограмма", "semen analysis"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="в пределах референса",
    plausible_min=0, plausible_max=1, validity_months=6,
))

# ---------------- imaging / services (075 & checkups) ----------------
_add(Indicator(
    code="fluoro", name="Флюорография (рентген ОГК)",
    aliases=("флюорография", "рентген легких", "рентген огк", "fluorography", "x-ray chest", "рентген грудной клетки"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="без патологии",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="ecg", name="ЭКГ",
    aliases=("экг", "ecg", "электрокардиография", "электрокардиограмма"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="синусовый ритм",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="us_abd", name="УЗИ брюшной полости",
    aliases=("узи брюшной полости", "узи абдоминальное", "abdominal ultrasound"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="без патологии",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="us_thyroid", name="УЗИ щитовидной железы",
    aliases=("узи щитовидной железы", "thyroid ultrasound"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="диффузные/узловые изменения — по описанию",
    plausible_min=0, plausible_max=1, validity_months=12,
))
_add(Indicator(
    code="therapy", name="Консультация терапевта",
    aliases=("терапевт", "консультация терапевта", "general practitioner", "врач общей практики"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="услуга",
    plausible_min=0, plausible_max=1, validity_months=12, is_analysis=False,
))
_add(Indicator(
    code="dental", name="Осмотр стоматолога",
    aliases=("стоматолог", "осмотр стоматолога", "dentist"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="услуга",
    plausible_min=0, plausible_max=1, validity_months=12, is_analysis=False,
))
_add(Indicator(
    code="dermo", name="Дерматоскопия (профилактика меланомы)",
    aliases=("дерматоскопия", "дерматолог", "dermatoscopy", "осмотр дерматолога"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="услуга/исследование",
    plausible_min=0, plausible_max=1, validity_months=12, is_analysis=False,
))
_add(Indicator(
    code="femoral", name="Фемо-визор (феморальная артерия, скрининг)",
    aliases=("фемовизор", "фемо-визор", "ultrasound iliac arteries"),
    unit="—", unit_aliases=("—", "-"),
    ref_low=None, ref_high=None, ref_text="атеросклероз — по описанию",
    plausible_min=0, plausible_max=1, validity_months=24,
))


# ---------------- helpers ----------------

def get(code_or_name: str) -> Indicator | None:
    """Resolve by exact code or fuzzy name alias (lowercased, trimmed)."""
    s = code_or_name.strip()
    if s in CATALOG:
        return CATALOG[s]
    key = " ".join(s.lower().split())
    if key in ALIASES:
        return CATALOG[ALIASES[key]]
    # try substring match on aliases (lab names vary)
    for alias, code in ALIASES.items():
        if len(alias) >= 4 and alias in key:
            return CATALOG[code]
    return None


def all_indicators() -> list[Indicator]:
    return list(CATALOG.values())


def to_standard_unit(value: float, unit: str, ind: Indicator) -> tuple[float, str] | None:
    """Convert a lab value to the indicator's standard unit. Returns (value, unit) or None
    if the unit isn't understood (-> caller flags it)."""
    u = " ".join(unit.lower().replace("−", "-").replace("–", "-").split())
    # known confusables from real lab PDFs (font issues, mixed scripts) —
    # keys deliberately contain LATIN lookalikes, written with escapes:
    CONFUSABLES = {
        "n\u043c\u043e\u043b\u044c/\u043b": "\u043d\u043c\u043e\u043b\u044c/\u043b",  # nmol/L
        "m\u0433/\u043b": "\u043c\u0433/\u043b",  # mg/L
        "mmol/l": "\u043c\u043c\u043e\u043b\u044c/\u043b",  # mmol/L
        "u\u043c\u043e\u043b/\u043b": "\u043c\u043a\u043c\u043e\u043b\u044c/\u043b",  # umol/L
    }
    u = CONFUSABLES.get(u, u)
    std = ind.unit.lower()
    # cross-unit conversions take priority over the alias match
    if ind.code == "hb" and u in ("g/dl", "г/дл"):
        return value * 10, ind.unit
    if ind.code == "vitd" and u in ("ng/ml", "нг/мл", "ng/dl"):
        return value * 2.5, ind.unit  # ng/mL & ng/dL -> nmol/L
    if u == std or u in (a.lower() for a in ind.unit_aliases):
        return value, ind.unit
    if ind.code == "rh":
        if u.startswith("+") or u in ("положительный", "полож", "positive"):
            return 1, ind.unit
        if u.startswith("−") or u.startswith("-") or u in ("отрицательный", "отриц", "negative"):
            return -1, ind.unit
    if ind.code == "ab0" and u == "группа":
        num = round(value)
        if 1 <= num <= 4:
            return float(num), ind.unit
    return None
