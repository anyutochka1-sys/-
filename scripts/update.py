"""Import Rosstat's final annual regional wage table; fail closed on layout changes."""
import datetime as dt
import io
import hashlib
import json
import re
import ssl
import socket
import tempfile
from urllib.parse import urlparse
import urllib.request
from pathlib import Path

from openpyxl import load_workbook
import certifi

SOURCE = "https://www.rosstat.gov.ru/storage/mediabank/tab4-zpl_2025.xlsx"
ROOT_CA = "https://gu-st.ru/content/Other/doc/russiantrustedca.pem"
ROOT_FINGERPRINT = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"
SUB_FINGERPRINT = "bbbde2103e790b999ec62bd03cf625a5a2e7c316e10afe6a490eedead8b3fd9b"
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
    # Bootstrap only this CA download; trust it solely when its DER fingerprint matches.
    bootstrap = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(ROOT_CA, timeout=30, context=bootstrap) as response:
            root = response.read()
    except Exception as exc:
        raise RuntimeError(f"Root CA download: {exc}") from exc
    certificates = re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", root, re.S)
    fingerprints = {hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))).hexdigest() for pem in certificates}
    if not {ROOT_FINGERPRINT, SUB_FINGERPRINT} <= fingerprints:
        raise ValueError("Official certificate chain fingerprints mismatch")
    base_context = ssl.create_default_context(cafile=certifi.where())
    base_context.load_verify_locations(cadata=root.decode("ascii"))
    # The Rosstat server omits its intermediate CA; trust the individually pinned sub CA.
    base_context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0 (regional-wage-reference)"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=base_context) as response:
            raw = response.read()
    except Exception as exc:
        try:
            host = urlparse(SOURCE).hostname
            with socket.create_connection((host, 443), timeout=15) as sock:
                with bootstrap.wrap_socket(sock, server_hostname=host) as tls:
                    pem = ssl.DER_cert_to_PEM_cert(tls.getpeercert(binary_form=True))
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem") as temp:
                temp.write(pem)
                temp.flush()
                certificate = ssl._ssl._test_decode_cert(temp.name)
            destination = f"issuer={certificate.get('issuer')}, subject={certificate.get('subject')}"
        except Exception as probe:
            destination = f"certificate probe: {probe}"
        raise RuntimeError(f"Rosstat workbook download ({destination}): {exc}") from exc
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
