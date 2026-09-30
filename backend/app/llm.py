"""LLM wrapper — единая обёртка над моделью (plan §0).

- provider "mock":   детерминированный офлайн-провайдер (демо без сети, CI).
  Он не "понимает" текст: он ищет строки по словарю показателей и возвращает
  те же данные в строгую JSON-схему. Достаточно для синтетических PDF и CI.
- provider "openai": любой OpenAI-совместимый endpoint.
  Qwen cloud:  LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1, LLM_MODEL=qwen3.8-max
  vLLM/SGLang: LLM_BASE_URL=http://gpu-host:8000/v1,                              LLM_MODEL=Qwen3.8-27B
  Переход = смена трёх переменных окружения, код не меняется.

Схема ответа модели (строгая, только JSON):
{
  "indicators": [
    {"name": "...", "value": "...", "unit": "...",
     "reference": "...", "date": "YYYY-MM-DD"}
  ],
  "report_date": "YYYY-MM-DD" | null
}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import get_settings
from . import indicators as ind


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    indicators: list[dict]      # [{"name","value","unit","reference","date"}]
    report_date: str | None
    provider: str
    model: str
    raw: str


SYSTEM_PROMPT = (
    "Ты — извлекающий модул медицинской лаборатории. Выдавай ТОЛЬКО валидный JSON "
    "без пояснений, без markdown, без полей вне схемы. Схема:\n"
    '{"indicators":[{"name":"<название показателя>","value":"<значение, числом если число>",'
    '"unit":"<единица>","reference":"<референс из отчёта>","date":"YYYY-MM-DD или null"}],'
    '"report_date":"YYYY-MM-DD или null"}\n'
    "Включай только количественные/качественные лабораторные показатели из отчёта. "
    "Не выдумывай значения. Дату бери из заголовка отчёта (день сдачи/анализа). "
    "Если значения нет — value=null."
)


def _user_prompt(text: str) -> str:
    return f"Текст отчёта:\n---\n{text[:24000]}\n---\nИзвлеки показатели в JSON по схеме."


# ---------------- mock provider (deterministic, offline) ----------------

_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _parse_value(s: str) -> float | str | None:
    s = s.strip()
    if not s:
        return None
    if _NUM_RE.match(s):
        return float(s.replace(",", "."))
    return s


def _match_indicator(line: str) -> "ind.Indicator | None":
    """Best indicator for a lab row: prefer a prefix match (lab rows start with the
    name), fall back to substring. Longest alias wins — 'гликированный гемоглобин'
    beats 'гемоглобин' on the same line."""
    key = " ".join(line.lower().split())
    best, best_len = None, 0
    for ind_obj in ind.CATALOG.values():
        for alias in (ind_obj.name.lower(),) + ind_obj.aliases:
            a = " ".join(alias.split())
            if key.startswith(a) and len(a) > best_len:
                best, best_len = ind_obj, len(a)
    if best is not None:
        return best
    best, best_len = None, 0
    for ind_obj in ind.CATALOG.values():
        for alias in (ind_obj.name.lower(),) + ind_obj.aliases:
            a = " ".join(alias.split())
            if len(a) >= 4 and a in key and len(a) > best_len:
                best, best_len = ind_obj, len(a)
    return best


ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}


def mock_structuring(text: str) -> LLMResult:
    """Rule-based extractor over the indicator dictionary. Deterministic: the same
    text always gives the same output — what a correct LLM would produce on clean
    lab text. Used for demo, CI, and as a fallback when the model is unreachable."""
    settings = get_settings()
    lines = [ln.strip(" \t|") for ln in text.splitlines()]
    found: list[dict] = []
    seen: set[str] = set()
    report_date = None
    date_re = re.compile(r"\b(\d{4})[./-](\d{2})[./-](\d{2})\b|\b(\d{2})[./](\d{2})[./](\d{4})\b")

    for i, line in enumerate(lines):
        if not line or line in seen:
            continue
        m = date_re.search(line)
        if m and report_date is None and any(k in line.lower() for k in ("дата", "date", "взят")):
            if m.group(1):
                report_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            else:
                report_date = f"{m.group(6)}-{m.group(5)}-{m.group(4)}"

        ind_obj = _match_indicator(line)
        if ind_obj is None or ind_obj.code in seen:
            continue
        seen.add(ind_obj.code)

        # value+unit: try this line, then the next (some labs put them on 2 lines)
        value: str | float | None = None
        unit: str | None = None
        for cand in (line, lines[i + 1] if i + 1 < len(lines) else ""):
            parts = [p.strip() for p in re.split(r"[\t\x00|\s]+", cand) if p.strip()]
            if ind_obj.code == "ab0":
                value = next((p for p in parts if p.upper().strip("()") in ROMAN), None)
                unit = "группа" if value else None
                break
            if ind_obj.code == "rh":
                v = next((p for p in parts if p in ("+", "−", "-") or
                          p.lower() in ("положительный", "отрицательный")), None)
                value = v
                unit = v
                break
            for j, p in enumerate(parts):
                pv = _parse_value(p)
                if isinstance(pv, float) and j + 1 < len(parts):
                    value = pv
                    unit = parts[j + 1]
                    break
            if value is not None:
                break
            if parts and value is None and (ref := _parse_value(parts[0])) is not None:
                value = ref  # value-only line, unit on the same/next token failed
        if value is None:
            continue
        if isinstance(value, float):
            value = f"{value:g}"

        dm = date_re.search(line)
        if dm:
            d = (f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}" if dm.group(1)
                 else f"{dm.group(6)}-{dm.group(5)}-{dm.group(4)}")
        else:
            d = report_date
        found.append({
            "name": ind_obj.name,
            "value": value,
            "unit": unit or ind_obj.unit,
            "reference": ind_obj.ref_text,
            "date": d,
        })
        if len(found) >= 40:
            break
    return LLMResult(found, report_date, "mock", "mock-extractor", json.dumps(found, ensure_ascii=False))


# ---------------- openai-compatible provider ----------------

def openai_structuring(text: str) -> LLMResult:
    import httpx

    s = get_settings()
    s.require_llm_key()
    body = {
        "model": s.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(text)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"} if s.llm_json_mode else None,
    }
    if body.get("response_format") is None:
        body.pop("response_format")
    try:
        r = httpx.post(
            f"{s.llm_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {s.llm_api_key}"},
            timeout=s.llm_timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        raw = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"LLM request failed: {e}") from e

    # extract JSON object (models sometimes wrap it)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise LLMError(f"LLM returned no JSON: {raw[:200]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned invalid JSON: {e}") from e

    inds = obj.get("indicators", [])
    clean = []
    for it in inds:
        if not isinstance(it, dict):
            continue
        clean.append({
            "name": str(it.get("name", ""))[:200],
            "value": it.get("value"),
            "unit": str(it.get("unit", ""))[:60] if it.get("unit") else None,
            "reference": str(it.get("reference", ""))[:200] if it.get("reference") else None,
            "date": it.get("date"),
        })
    return LLMResult(clean, obj.get("report_date"), s.llm_provider, s.llm_model, raw)


def structure_report(text: str) -> LLMResult:
    """Route to the configured provider."""
    s = get_settings()
    if s.llm_provider == "mock":
        return mock_structuring(text)
    if s.llm_provider == "openai":
        return openai_structuring(text)
    raise LLMError(f"unknown LLM_PROVIDER={s.llm_provider!r} (use 'mock' or 'openai')")
