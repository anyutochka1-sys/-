"""Import Rosstat's final annual regional wage table; fail closed on layout changes."""
import datetime as dt
import io
import json
import re
import ssl
import urllib.request
from pathlib import Path

from openpyxl import load_workbook
import certifi

SOURCE = "https://www.rosstat.gov.ru/storage/mediabank/tab4-zpl_2025.xlsx"
DATA = Path("data/salaries.json")
STATUS = Path("data/import-status.json")
EFFECTIVE = {2024: "2026-03-01", 2025: "2026-06-01"}
REGION_START = re.compile(r"^(?:Республика |Край |Область |Автономн|г\. |Город |Москва$|Санкт-Петербург$|Севастополь$)", re.I)


def number(value):
    if isinstance(value, (int, float)) and value > 1000:
        return round(float(value), 2)
    if isinstance(value, str):
        text = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if re.fullmatch(r"\d{4,6}(?:\.\d{1,2})?", text):
            return round(float(text), 2)
    return None


def region(value):
    if not isinstance(value, str):
        return None
    name = re.sub(r"\s+", " ", value).strip().replace("Ё", "Е")
    if (REGION_START.search(name) or name.endswith((" область", " край", " автономный округ"))) and not any(
        marker in name.lower() for marker in ("российская федерация", "федеральный округ", "в том числе", "районы крайнего")
    ):
        return name
    return None


def extract(book):
    years = {}
    for sheet in book.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        for header_index, row in enumerate(rows):
            columns = {i: int(v) for i, v in enumerate(row) if str(v).strip() in ("2024", "2025", "2026")}
            if not columns:
                continue
            for values in rows[header_index + 1:]:
                label = next((region(v) for v in values[:4] if region(v)), None)
                if not label:
                    continue
                for col, year in columns.items():
                    if col < len(values) and (salary := number(values[col])):
                        years.setdefault(year, {})[label] = salary
    return years


def main():
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0 (regional-wage-reference)"})
    with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as response:
        raw = response.read()
    if not raw.startswith(b"PK"):
        raise ValueError("Rosstat response is not an XLSX file")
    found = extract(load_workbook(io.BytesIO(raw), read_only=True, data_only=True))
    for year, expected in ((2024, 57133.1), (2025, 66836.8)):
        actual = found.get(year, {}).get("Республика Мордовия")
        if actual is None or abs(actual - expected) > 1:
            raise ValueError(f"Year {year}: Mordovia cross-check failed ({actual})")
    existing = json.loads(DATA.read_text(encoding="utf-8"))
    checked = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for year, regions in found.items():
        if len(regions) < 80:
            raise ValueError(f"Only {len(regions)} regions found for {year}; source layout needs review")
        existing["years"][str(year)] = {
            name: {"salary": salary, "effective_from": EFFECTIVE.get(year), "source": SOURCE, "checked_at": checked}
            for name, salary in regions.items()
        }
    if not any(str(y) in existing["years"] for y in EFFECTIVE):
        raise ValueError("No confirmed annual data extracted")
    DATA.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        STATUS.write_text(json.dumps({"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "failed", "reason": str(exc)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    else:
        STATUS.write_text(json.dumps({"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "ok"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
