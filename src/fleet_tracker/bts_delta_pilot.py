"""Read-only quality gate for official BTS DL reporting-carrier records (Jan/Jul 2025)."""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
from urllib.request import urlopen, Request
import zipfile

URL = "https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_{}.zip"
FIELDS = {
    "date": ["FlightDate", "FL_DATE"], "carrier": ["Reporting_Airline"],
    "flight": ["Flight_Number_Reporting_Airline"], "origin": ["Origin"],
    "dest": ["Dest"], "scheddep": ["CRSDepTime", "CRS_DEP_TIME"],
    "schedarr": ["CRSArrTime", "CRS_ARR_TIME"], "tail": ["Tail_Number", "TAIL_NUM"],
    "cancel": ["Cancelled"], "divert": ["Diverted"],
    "on15": ["ArrDel15", "ARR_DEL15"], "arrdelay": ["ArrDelay", "ARR_DELAY"],
}

def columns(headers):
    lookup = {}
    for h in headers:
        k = re.sub("[^a-z0-9]", "", h.casefold())
        if k in lookup:
            raise ValueError("Duplicate normalized field: " + k)
        lookup[k] = h
    out = {}
    for name, aliases in FIELDS.items():
        out[name] = next((lookup[a.casefold().replace("_", "")] for a in aliases
                          if a.casefold().replace("_", "") in lookup), None)
        if out[name] is None:
            raise ValueError(f"Missing required source field: {name}")
    return out

def flag(s):
    s = str(s or "").strip()
    return 0 if s in ("0", "0.0") else 1 if s in ("1", "1.0") else None

def flight_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError("Unexpected FL_DATE format")

def analyze(archive: Path, month: int):
    if month not in (1, 7):
        raise ValueError("Only Jan and July 2025 allowed")
    if archive.stat().st_size > 150_000_000:
        raise ValueError("Source ZIP too large for bounded pilot")
    sha = hashlib.sha256()
    with archive.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    with zipfile.ZipFile(archive) as z:
        entries = [x for x in z.infolist() if x.filename.lower().endswith(".csv") and not x.is_dir()]
        if len(entries) != 1 or entries[0].file_size > 1_000_000_000:
            raise ValueError("Expected one bounded CSV in ZIP")
        with z.open(entries[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("Missing header")
            cols = columns(reader.fieldnames)
            def get(row, f):
                return (row.get(cols[f]) or "").strip()
            counters = dict(all=0, dl=0, status_valid=0, canceled=0, diverted=0,
                            eligible=0, arr15_valid=0, ontime=0, delay_valid=0,
                            flag_conflicts=0, tail_present=0, missing_route=0,
                            missing_clock=0, duplicates=0)
            dates, keys = set(), set()
            for r in reader:
                counters["all"] += 1
                if get(r, "carrier").upper() != "DL":
                    continue
                counters["dl"] += 1
                d = flight_date(get(r, "date"))
                if (d.year, d.month) != (2025, month):
                    raise ValueError("Wrong month in DL source rows")
                dates.add(d.day)
                k = (d, get(r, "flight"), get(r, "origin"), get(r, "dest"), get(r, "scheddep"))
                if k in keys:
                    counters["duplicates"] += 1
                keys.add(k)
                if not get(r, "origin") or not get(r, "dest"):
                    counters["missing_route"] += 1
                if not get(r, "scheddep") or not get(r, "schedarr"):
                    counters["missing_clock"] += 1
                c, v = flag(get(r, "cancel")), flag(get(r, "divert"))
                if c is None or v is None:
                    continue
                counters["status_valid"] += 1
                counters["canceled"] += c
                counters["diverted"] += v
                if c or v:
                    continue
                counters["eligible"] += 1
                counters["tail_present"] += bool(get(r, "tail"))
                on15 = flag(get(r, "on15"))
                if on15 is None:
                    continue
                counters["arr15_valid"] += 1
                counters["ontime"] += (on15 == 0)
                try:
                    delay = float(get(r, "arrdelay"))
                except ValueError:
                    continue
                counters["delay_valid"] += 1
                counters["flag_conflicts"] += ((delay >= 15) != bool(on15))
    n, e, a, dv = (counters[x] for x in ("dl", "eligible", "arr15_valid", "delay_valid"))
    if not n:
        raise ValueError("No Reporting_Airline=DL records")
    def pct(x, total):
        return round(x / total, 6) if total else None
    gate = (n >= 1000 and len(dates) == 31
            and counters["status_valid"] / n >= .995
            and e > 0 and a / e >= .98 and dv / a >= .98
            and counters["flag_conflicts"] / dv <= .001
            and counters["duplicates"] / n <= .001
            and counters["missing_route"] == 0 and counters["missing_clock"] == 0)
    return {
        "source_url": URL.format(month), "source_zip_sha256": sha.hexdigest(),
        "source_csv": entries[0].filename, "year": 2025, "month": month,
        "reporting_carrier_filter": "Reporting_Airline=DL",
        "counts": counters, "distinct_flight_dates": len(dates),
        "cancellation_rate_scheduled": pct(counters["canceled"], n),
        "diversion_rate_scheduled": pct(counters["diverted"], n),
        "arrival_ontime_rate_completed_valid": pct(counters["ontime"], a),
        "arrival_ontime_denominator": a,
        "arrival_flag_coverage_completed": pct(a, e),
        "tail_coverage_completed": pct(counters["tail_present"], e),
        "core_kpi_gate": "GO" if gate else "REVISE",
        "tail_sequence_gate": "CANDIDATE_ONLY" if e and counters["tail_present"] / e >= .90 else "REVISE",
    }

def download(month, path):
    req = Request(URL.format(month), headers={"User-Agent": "aviation-portfolio-research/1.0"})
    with urlopen(req, timeout=75) as response, path.open("wb") as f:
        size = 0
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            size += len(chunk)
            if size > 150_000_000:
                raise ValueError("Download exceeded 150MB")
            f.write(chunk)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--download", action="store_true")
    p.add_argument("--january", type=Path)
    p.add_argument("--july", type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args(argv)
    if a.download and (a.january or a.july):
        p.error("Choose --download or local archives")
    if not a.download and not (a.january and a.july):
        p.error("Provide --download or both --january and --july")
    with tempfile.TemporaryDirectory(prefix="bts-dl-pilot-") as temp:
        archives = {1: a.january, 7: a.july}
        if a.download:
            archives = {m: Path(temp) / f"{m}.zip" for m in (1, 7)}
            for m, path in archives.items():
                download(m, path)
        results = [analyze(archives[m], m) for m in (1, 7)]
    outcome = "GO" if all(r["core_kpi_gate"] == "GO" for r in results) else "REVISE"
    report = {
        "description": "BTS DL reporting-carrier domestic operations, not all Delta-marketed flights",
        "arrival_metric": "ArrDel15=0 / non-canceled non-diverted rows with valid ArrDel15",
        "cancellation_metric": "Cancelled=1 / scheduled DL rows",
        "diversion_metric": "Diverted=1 / scheduled DL rows",
        "both_months_core_gate": outcome,
        "months": results,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"outcome": outcome,
                      "months": [{"month": r["month"], "dl_rows": r["counts"]["dl"],
                                  "status": r["core_kpi_gate"]} for r in results]}, indent=2))
    return 0 if outcome == "GO" else 2

if __name__ == "__main__":
    raise SystemExit(main())
