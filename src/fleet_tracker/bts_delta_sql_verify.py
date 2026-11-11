"""Independent SQLite check of the official BTS Delta reporting-carrier pilot.
Flight rows remain only in temporary in-memory SQLite; nothing raw is committed.
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

FIELDS = ("FlightDate","Reporting_Airline","Flight_Number_Reporting_Airline",
          "Origin","Dest","CRSDepTime","Cancelled","Diverted","ArrDel15",
          "ArrDelay","Tail_Number")

def binary(value):
    try:
        v=Decimal(str(value).strip())
        return int(v) if v in (Decimal(0),Decimal(1)) else None
    except (InvalidOperation,ValueError):
        return None

def number(value):
    try:
        return float(Decimal(str(value).strip()))
    except (InvalidOperation,ValueError):
        return None

def aggregate(path: Path):
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    db=sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE operations(
        flightdate TEXT, flightnum TEXT, origin TEXT, dest TEXT, crsdep TEXT,
        cancelled INTEGER, diverted INTEGER, arr15 INTEGER, arrdelay REAL, tail TEXT)""")
    with zipfile.ZipFile(path) as z:
        csvs=[f for f in z.infolist() if f.filename.lower().endswith(".csv")]
        if len(csvs)!=1 or csvs[0].file_size>1_000_000_000:
            raise ValueError("Expected exactly one bounded CSV")
        with z.open(csvs[0]) as stream, io.TextIOWrapper(stream,encoding="utf-8-sig",newline="") as text_stream:
            reader=csv.DictReader(text_stream)
            if not set(FIELDS).issubset(set(reader.fieldnames or [])):
                raise ValueError("Actual BTS CSV missing required SQL-verifier header")
            batch=[]
            for row in reader:
                if row["Reporting_Airline"]!="DL":
                    continue
                batch.append((row["FlightDate"],row["Flight_Number_Reporting_Airline"],
                              row["Origin"],row["Dest"],row["CRSDepTime"],
                              binary(row["Cancelled"]),binary(row["Diverted"]),
                              binary(row["ArrDel15"]),number(row["ArrDelay"]),row["Tail_Number"] or ""))
                if len(batch)>=5000:
                    db.executemany("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?)",batch)
                    batch.clear()
            if batch:
                db.executemany("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?)",batch)
    query="""SELECT COUNT(*),
        SUM(CASE WHEN cancelled IN (0,1) AND diverted IN (0,1) THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diverted=1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=0 AND diverted=0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=0 AND diverted=0 AND arr15 IN (0,1) THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=0 AND diverted=0 AND arr15=0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=0 AND diverted=0 AND arr15 IN (0,1)
                 AND arrdelay IS NOT NULL THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=0 AND diverted=0 AND arr15 IN (0,1) AND arrdelay IS NOT NULL
                 AND ((arrdelay >=15 AND arr15<>1) OR (arrdelay<15 AND arr15<>0))
            THEN 1 ELSE 0 END),
        SUM(CASE WHEN cancelled=0 AND diverted=0 AND trim(tail)<>'' THEN 1 ELSE 0 END),
        SUM(CASE WHEN origin='' OR dest='' THEN 1 ELSE 0 END),
        SUM(CASE WHEN crsdep='' THEN 1 ELSE 0 END),
        COUNT(DISTINCT flightdate) FROM operations"""
    names=("dl","status_valid","canceled","diverted","eligible","arr15_valid","ontime",
           "delay_valid","flag_conflicts","tail_present","missing_route","missing_dep","days")
    result=dict(zip(names,(int(v or 0) for v in db.execute(query).fetchone())))
    result["duplicates"]=db.execute("""SELECT COALESCE(SUM(n-1),0) FROM(
        SELECT COUNT(*) n FROM operations GROUP BY flightdate,flightnum,origin,dest,crsdep
        HAVING n>1)""").fetchone()[0]
    result["sha256"]=sha
    db.close()
    return result

def verify(month, archive, report):
    sql=aggregate(archive)
    primary=next(m for m in report["months"] if m["month"]==month)
    keys=("dl","status_valid","canceled","diverted","eligible","arr15_valid","ontime",
          "delay_valid","flag_conflicts","tail_present","missing_route","duplicates")
    bad={k:(sql[k],primary["counts"][k]) for k in keys if sql[k]!=primary["counts"][k]}
    if sql["days"]!=primary["distinct_flight_dates"]:
        bad["days"]=(sql["days"],primary["distinct_flight_dates"])
    if sql["sha256"]!=primary["source_zip_sha256"]:
        bad["sha256"]=(sql["sha256"],primary["source_zip_sha256"])
    if sql["missing_dep"]>primary["counts"]["missing_clock"]:
        bad["missing_dep"]=(sql["missing_dep"],primary["counts"]["missing_clock"])
    if bad:
        raise ValueError(f"Independent SQL disagreed for month {month}: {bad}")
    return sql

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january",type=Path,required=True)
    p.add_argument("--july",type=Path,required=True)
    p.add_argument("--expected",type=Path,required=True)
    a=p.parse_args(argv)
    report=json.loads(a.expected.read_text())
    jan=verify(1,a.january,report)
    jul=verify(7,a.july,report)
    print(json.dumps({"verdict":"INDEPENDENT_SQL_PARITY_PASS",
                      "jan_rows":jan["dl"],"jul_rows":jul["dl"],
                      "exact_count_metrics_compared_per_month":12},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
