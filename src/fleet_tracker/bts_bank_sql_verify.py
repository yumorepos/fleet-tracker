"""Independent SQLite verification of Delta local-bank and destination-mix audit.

Re-reads the exact BTS ZIP sources without calling the primary bank analyzer,
clock helper, group counters, or matching routine. In-memory flight rows only.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import zipfile

from fleet_tracker.bts_delta_pilot import flight_date
from fleet_tracker.bts_driver_profile import EXPECTED_SHA

FIELDS = (
    "FlightDate", "Reporting_Airline", "Origin", "Dest",
    "CRSDepTime", "Cancelled", "Diverted", "ArrDel15",
)
BANKS = ("00-05", "06-11", "12-17", "18-23")
GROUPS = ("ATL_origin", "Other_origin")


def clock_group(s: str) -> str:
    try:
        x = Decimal(str(s or "").strip())
    except InvalidOperation as exc:
        raise ValueError("Invalid scheduled clock in independent SQL check") from exc
    if not x.is_finite() or x != int(x):
        raise ValueError("Invalid noninteger scheduled clock")
    n = int(x)
    if n == 2400:
        return BANKS[0]
    h, m = divmod(n, 100)
    if h not in range(24) or m not in range(60):
        raise ValueError("Invalid scheduled clock minutes")
    return BANKS[h // 6]


def numeric_flag(s: str) -> int:
    try:
        x = Decimal(str(s or "").strip())
    except InvalidOperation as exc:
        raise ValueError("Invalid binary status field") from exc
    if x not in (0, 1):
        raise ValueError("Binary status not 0 or 1")
    return int(x)


def load_and_query(archive: Path, month: int, min_stratum: int = 25) -> dict:
    if month not in EXPECTED_SHA or archive.stat().st_size > 150_000_000:
        raise ValueError("Unexpected monthly input")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_SHA[month]:
        raise ValueError("Source checksum mismatch in independent SQL verification")
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("""CREATE TABLE flights (
            origin_group TEXT NOT NULL, bank TEXT NOT NULL,
            dest TEXT NOT NULL, canceled INTEGER NOT NULL,
            diverted INTEGER NOT NULL, arr15 INTEGER
        )""")
        rows = []
        with zipfile.ZipFile(archive) as z:
            members = [f for f in z.infolist() if f.filename.lower().endswith(".csv") and not f.is_dir()]
            if len(members) != 1 or members[0].file_size > 1_000_000_000:
                raise ValueError("Unexpected BTS source CSV contents")
            with z.open(members[0]) as raw, io.TextIOWrapper(
                    raw, encoding="utf-8-sig", newline="") as stream:
                source = csv.DictReader(stream)
                if not set(FIELDS).issubset(source.fieldnames or ()):
                    raise ValueError("Required source fields missing")
                for r in source:
                    if (r["Reporting_Airline"] or "").strip() != "DL":
                        continue
                    day = flight_date(r["FlightDate"])
                    if day.year != 2025 or day.month != month:
                        raise ValueError("Unexpected flight operation date")
                    origin = (r["Origin"] or "").strip().upper()
                    dest = (r["Dest"] or "").strip().upper()
                    if len(origin) != 3 or not origin.isalpha() or len(dest) != 3 or not dest.isalpha():
                        raise ValueError("Invalid three-letter airport identifier")
                    c, d = numeric_flag(r["Cancelled"]), numeric_flag(r["Diverted"])
                    if c and d:
                        raise ValueError("Contradictory flight status flags")
                    arr = None if c or d else numeric_flag(r["ArrDel15"])
                    rows.append(("ATL_origin" if origin == "ATL" else "Other_origin",
                                 clock_group(r["CRSDepTime"]), dest, c, d, arr))
                    if len(rows) >= 5000:
                        conn.executemany("INSERT INTO flights VALUES (?,?,?,?,?,?)", rows)
                        rows.clear()
                if rows:
                    conn.executemany("INSERT INTO flights VALUES (?,?,?,?,?,?)", rows)
        bank_sql = """
        SELECT origin_group, bank, COUNT(*) scheduled,
            SUM(canceled) canceled, SUM(diverted) diverted,
            SUM(CASE WHEN canceled=0 AND diverted=0 THEN 1 ELSE 0 END) valid_arrivals,
            SUM(CASE WHEN canceled=0 AND diverted=0 AND arr15=0 THEN 1 ELSE 0 END) on_time
        FROM flights GROUP BY origin_group, bank ORDER BY origin_group, bank
        """
        bank_data = { (grp, bank): {
            "origin_group": grp, "scheduled_local_bank": bank,
            "scheduled": int(sched), "canceled": int(cancel), "diverted": int(divert),
            "valid_arrivals": int(valid), "on_time": int(on)
        } for grp, bank, sched, cancel, divert, valid, on in conn.execute(bank_sql) }
        bank_rows = [
            bank_data.get((g, bank), {
                "origin_group": g, "scheduled_local_bank": bank,
                "scheduled": 0, "canceled": 0, "diverted": 0,
                "valid_arrivals": 0, "on_time": 0,
            }) for g in GROUPS for bank in BANKS
        ]
        match_sql = """
        WITH cells AS (
           SELECT origin_group, bank, dest,
             SUM(CASE WHEN arr15 IS NOT NULL THEN 1 ELSE 0 END) n,
             SUM(CASE WHEN arr15=0 THEN 1 ELSE 0 END) ont
           FROM flights
           GROUP BY origin_group, bank, dest
        )
        SELECT a.n, a.ont, b.n, b.ont
        FROM cells a JOIN cells b ON a.bank=b.bank AND a.dest=b.dest
        WHERE a.origin_group='ATL_origin' AND b.origin_group='Other_origin'
          AND a.n >= ? AND b.n >= ?
        ORDER BY a.bank, a.dest
        """
        matches = conn.execute(match_sql, (min_stratum, min_stratum)).fetchall()
        na, nb = sum(r[0] for r in matches), sum(r[2] for r in matches)
        total = na + nb
        total_a = sum(r["valid_arrivals"] for r in bank_rows if r["origin_group"] == "ATL_origin")
        total_b = sum(r["valid_arrivals"] for r in bank_rows if r["origin_group"] == "Other_origin")
        return {
            "source_sha256": digest.hexdigest(), "bank_rows": bank_rows,
            "matched_strata": len(matches),
            "atl_valid_arrivals_in_matched": na,
            "other_valid_arrivals_in_matched": nb,
            "atl_coverage_of_all_valid": round(na / total_a, 6) if total_a else None,
            "other_coverage_of_all_valid": round(nb / total_b, 6) if total_b else None,
            "matched_unadjusted_atl_rate": round(sum(r[1] for r in matches) / na, 6) if na else None,
            "matched_unadjusted_other_rate": round(sum(r[3] for r in matches) / nb, 6) if nb else None,
            "pooled_standardized_atl_rate": round(
                sum((a+b)*a_on/a for a,a_on,b,b_on in matches) / total, 6
            ) if total else None,
            "pooled_standardized_other_rate": round(
                sum((a+b)*b_on/b for a,a_on,b,b_on in matches) / total, 6
            ) if total else None,
            "pooled_standardized_atl_minus_other_pp": round(
                100 * (
                    sum((a+b)*a_on/a for a,a_on,b,b_on in matches)
                    - sum((a+b)*b_on/b for a,a_on,b,b_on in matches)
                ) / total, 3
            ) if total else None,
        }
    finally:
        conn.close()


def verify(archives: dict[int, Path], report: dict) -> dict:
    parts = report["months"]
    if len(parts) != 2 or {part["month"] for part in parts} != {1, 7}:
        raise ValueError("Expected exactly January and July 2025")
    result = []
    for month in (1, 7):
        primary = next(x for x in parts if x["month"] == month)
        computed = load_and_query(archives[month], month)
        if computed["source_sha256"] != primary["source_sha256"]:
            raise AssertionError("Independent source checksum mismatch")
        if computed["bank_rows"] != primary["bank_rows"]:
            raise AssertionError(f"Month {month}: bank counts disagree with independent SQL")
        profile = primary["shared_destination_bank"]
        for name, value in computed.items():
            if name in ("bank_rows", "source_sha256"):
                continue
            if profile[name] != value:
                raise AssertionError(f"Month {month}: matched comparison disagrees on {name}: {profile[name]} vs {value}")
        result.append({"month": month, "status": "INDEPENDENT_SQL_PARITY_PASS",
                       "matched_strata": computed["matched_strata"]})
    return {"verdict": "INDEPENDENT_SQL_PARITY_PASS", "months": result}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january", required=True, type=Path)
    p.add_argument("--july", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args(argv)
    result = verify({1: a.january, 7: a.july}, json.loads(a.report.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    if a.output.exists():
        raise FileExistsError("Refusing to overwrite independent verification report")
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
