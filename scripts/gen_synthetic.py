"""Generate SYNTHETIC, de-identified lab report PDFs for demo & tests.

Two "lab styles" to exercise the pipeline's robustness:
- lab_a: tabular text, one row per line:  name \t value \t unit \t ref
- lab_b: dot leaders, unit variants (г/дл for Hb, ng/dL for vit D)
Plus one SCAN-style PDF (image only, no text layer) to demo the 422 path.

All values are fictional. Run:  python -m scripts.gen_synthetic
Outputs: data/samples/*.pdf
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "samples"

FONT_CANDIDATES = [
    ROOT / "assets" / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"),
]


def _font() -> str:
    for p in FONT_CANDIDATES:
        if p.exists():
            return str(p)
    raise SystemExit("DejaVuSans.ttf not found — copy it to assets/ (see README)")


def _today() -> str:
    return dt.date.today().isoformat()


def _write_lines(path: Path, lines: list[str], start_y: int = 56, dy: int = 17) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = start_y
    for text in lines:
        page.insert_text((40, y), text, fontsize=9.5, fontname="dejavu", fontfile=_font())
        y += dy
    doc.save(str(path))
    doc.close()


def lab_a_pdf(path: Path) -> None:
    """Clean tabular report — the 'easy' case. Includes one real outlier (vit D low)."""
    d = _today()
    rows = [
        "Гемоглобин          138      г/л        120–160",
        "Лейкоциты           6.4      10^9/л     4.0–9.0",
        "Тромбоциты          264      10^9/л     180–320",
        "Глюкоза             5.1      ммоль/л    3.3–5.6",
        "Холестерин          4.9      ммоль/л    < 5.2",
        "АЛТ                 24       Ед/л       5–41",
        "АСТ                 21       Ед/л       5–35",
        "Креатинин           78       мкмоль/л   44–110",
        "ТТГ                 2.1      мМЕ/л      0.4–4.0",
        "Т4 свободный        16.2     пмоль/л    12–22",
        "Ферритин            13       нг/мл      12–250",
        "Витамин D (25-OH)   41       нмоль/л    50–250",
        "С-реактивный белок  1.8      мг/л       < 5",
        "Группа крови (АБ0)  II       группа     I–IV",
        "Резус-фактор        +        +          + / −",
    ]
    lines = [
        "ЛИК МЕДЛАБ «Алмалы» — аналитический отчёт",
        f"Дата исследования: {d}",
        "Пациент: Тестов Т. Т. (синтетические обезличенные данные)",
        "",
        "Показатель            Значение   Ед.      Референс",
    ] + rows + [
        "",
        "Вывод: показатели в пределах референса, кроме отмеченных.",
    ]
    _write_lines(path, lines)


def lab_b_pdf(path: Path) -> None:
    """Messier lab: dot leaders + unit variants that must be normalised
    (г/дл = 10x г/л; ng/dL = 2.5x нмоль/л). Includes real outliers:
    TSH slightly low (borderline), vit D low (abnormal), ferritin high (abnormal)."""
    d = _today()
    lines = [
        "«СИНТЕЗ-ЛАБ» — результат исследования (обезличенные данные)",
        f"Дата забора: {d[:4]}-{d[5:7]}.{d[8:10]}      № 000-000",
        "Пациент: Тестова А. А.   пол: ж",
        "",
        "Гемоглобин .................... 12.8 г/дл    (12–16 г/дл)",
        "Глюкоза ....................... 4.9 ммоль/л  (3.3–5.6)",
        "ТТГ ........................... 0.38 мМЕ/л   (0.4–4.0)",
        "Витамин D 25-OH ............... 16.4 ng/dL   (20–60 ng/dL)",
        "Ферритин ...................... 285 мкг/л    (12–250 нг/мл)",
        "Холестерин .................... 5.8 ммоль/л  (< 5.2)",
        "Креатинин ..................... 96 мкмоль/л  (44–110)",
        "",
        "Примечание: в скобках — референс лаборатории.",
    ]
    _write_lines(path, lines)


def scan_pdf(path: Path) -> None:
    """Image-only PDF (no text layer) — must trigger the 422 scan path."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for text in ["СИНТЕЗ-ЛАБ (скан отчёта)", "Гемоглобин 138 г/л",
                 "Глюкоза 5.1 ммоль/л", "Ферритин 13 нг/мл",
                 "Витамин D 41 нмоль/л"]:
        page.insert_text((40, y), text, fontsize=12, fontname="dejavu", fontfile=_font())
        y += 30
    pix = page.get_pixmap(dpi=100)
    img = path.with_suffix(".png")
    pix.save(str(img))
    doc2 = pymupdf.open()
    p2 = doc2.new_page(width=595, height=842)
    p2.insert_image(p2.rect, filename=str(img))
    doc2.save(str(path))
    doc2.close()
    doc.close()
    img.unlink(missing_ok=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lab_a_pdf(OUT / "lab_a_text.pdf")
    lab_b_pdf(OUT / "lab_b_text.pdf")
    scan_pdf(OUT / "lab_scan.pdf")
    print(f"written to {OUT}:")
    for f in sorted(OUT.glob("*.pdf")):
        print(f"  {f.name}  ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
