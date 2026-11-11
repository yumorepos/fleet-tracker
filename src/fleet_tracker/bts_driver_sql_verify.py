"""Independent SQLite aggregation check for the BTS Delta airport/cause profile.

Do not call the primary profile's row processor, counters, segment or ratios.
Archived source rows are used in-memory only on the ephemeral research runner.
"""
from __future__ import annotations
import argparse
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import zipfile

EXPECTED_SHA={
  1:"868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf",
  7:"74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19"
}
FIELDS=("Origin","Reporting_Airline","Cancelled","Diverted","ArrDel15",
        "ArrDelay","CarrierDelay","WeatherDelay","NASDelay","SecurityDelay",
        "LateAircraftDelay")
CAUSES=("CarrierDelay","WeatherDelay","NASDelay","SecurityDelay","LateAircraftDelay")

def number(s):
    try:
        d=Decimal(str(s or "").strip())
        return float(d) if d.is_finite() else None
    except InvalidOperation:
        return None

def binary(s):
    x=number(s)
    return int(x) if x in (0,1) else None

def new_db():
    db=sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE flights(
        origin TEXT, canceled INTEGER, diverted INTEGER,
        arr15 INTEGER, arrdelay REAL, carrier REAL, weather REAL,
        nas REAL, security REAL, lateaircraft REAL
    )""")
    return db

def import_row(r):
    return (
      (r["Origin"] or "").strip().upper(),
      binary(r["Cancelled"]),binary(r["Diverted"]),binary(r["ArrDel15"]),
      number(r["ArrDelay"]),*(number(r[k]) for k in CAUSES)
    )

def insert_rows(db,rows):
    db.executemany("INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?)",rows)

SQL="""
WITH classified AS (
 SELECT *,
   CASE WHEN canceled=0 AND diverted=0 THEN 1 ELSE 0 END AS eligible,
   CASE WHEN canceled=0 AND diverted=0 AND arr15=1 AND
       carrier IS NOT NULL AND carrier>=0 AND
       weather IS NOT NULL AND weather>=0 AND
       nas IS NOT NULL AND nas>=0 AND
       security IS NOT NULL AND security>=0 AND
       lateaircraft IS NOT NULL AND lateaircraft>=0
     THEN 1 ELSE 0 END AS complete_causes
 FROM flights
),
two_grains AS (
 SELECT 'ALL_DL' AS grp, * FROM classified
 UNION ALL
 SELECT CASE WHEN origin='ATL' THEN 'ATL_origin' ELSE 'Other_origin' END AS grp,
        * FROM classified
)
SELECT grp,
 COUNT(*) scheduled,
 SUM(CASE WHEN canceled=1 THEN 1 ELSE 0 END) canceled,
 SUM(CASE WHEN diverted=1 THEN 1 ELSE 0 END) diverted,
 SUM(eligible) completed,
 SUM(CASE WHEN eligible=1 AND arr15=0 THEN 1 ELSE 0 END) on_time,
 SUM(CASE WHEN eligible=1 AND arr15=1 THEN 1 ELSE 0 END) late_arrival_15,
 SUM(CASE WHEN complete_causes=1 THEN 1 ELSE 0 END) complete,
 SUM(CASE WHEN eligible=1 AND arr15=1 AND complete_causes=0
              THEN 1 ELSE 0 END) missing_causes,
 SUM(CASE WHEN complete_causes=1 AND lateaircraft>0
              THEN 1 ELSE 0 END) positive_lateaircraft,
 SUM(CASE WHEN complete_causes=1 THEN lateaircraft ELSE 0 END) lateaircraft_minutes,
 SUM(CASE WHEN complete_causes=1 AND
       ABS(carrier+weather+nas+security+lateaircraft-arrdelay)>1
       THEN 1 ELSE 0 END) mismatch_cause_sum
FROM two_grains GROUP BY grp ORDER BY grp
"""

KEYS=("scheduled","canceled","diverted","completed","on_time","late_arrival_15",
      "complete","missing_causes","positive_lateaircraft","lateaircraft_minutes",
      "mismatch_cause_sum")

def grouped(db):
    rows=db.execute(SQL).fetchall()
    return {row[0]:dict(zip(KEYS,[float(x) if i==9 else int(x or 0)
                                  for i,x in enumerate(row[1:])]))
            for row in rows}

def read_zip(path,month):
    if month not in EXPECTED_SHA or path.stat().st_size>150_000_000:
        raise ValueError("Unsupported archive size or month")
    sha=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            sha.update(chunk)
    if sha.hexdigest()!=EXPECTED_SHA[month]:
        raise ValueError("Unexpected ZIP checksum")
    db=new_db()
    count=0
    with zipfile.ZipFile(path) as z:
        members=[x for x in z.infolist() if x.filename.lower().endswith(".csv") and not x.is_dir()]
        if len(members)!=1 or members[0].file_size>1_000_000_000:
            raise ValueError("Invalid archive format")
        with z.open(members[0]) as raw,io.TextIOWrapper(raw,encoding="utf-8-sig",newline="") as text:
            source=csv.DictReader(text)
            if not set(FIELDS).issubset(set(source.fieldnames or ())):
                raise ValueError("Missing BTS source columns")
            batch=[]
            for record in source:
                if (record["Reporting_Airline"] or "").strip()!="DL":
                    continue
                batch.append(import_row(record))
                count+=1
                if len(batch)>=4000:
                    insert_rows(db,batch)
                    batch.clear()
            if batch:
                insert_rows(db,batch)
    data=grouped(db)
    db.close()
    if data["ALL_DL"]["scheduled"]!=count:
        raise AssertionError("SQLite source row count mismatch")
    return {"month":month,"source_sha256":sha.hexdigest(),"groups":data}

def compare(sql_month,primary):
    if sql_month["source_sha256"]!=primary["source_sha256"]:
        raise AssertionError("Different source ZIP")
    for label,actual in sql_month["groups"].items():
        expected=primary["groups"].get(label)
        if expected is None:
            raise AssertionError("Missing reference group: "+label)
        pairs={
          "scheduled":"scheduled","canceled":"canceled","diverted":"diverted",
          "completed":"completed","on_time":"on_time","late_arrival_15":"late_arrival_15",
          "complete":"late_arrivals_with_complete_cause_detail",
          "missing_causes":"late_arrivals_missing_cause_detail",
          "positive_lateaircraft":None,
          "lateaircraft_minutes":None,
          "mismatch_cause_sum":"cause_minutes_vs_arrdelay_over_1min",
        }
        for key,ref in pairs.items():
            target=(expected["reported_positive_cause_flight_count"]["LateAircraftDelay"]
                    if key=="positive_lateaircraft" else
                    expected["reported_cause_minutes"]["LateAircraftDelay"]
                    if key=="lateaircraft_minutes" else expected[ref])
            if abs(actual[key]-target)>(.011 if key=="lateaircraft_minutes" else 0):
                raise AssertionError(f"Independent SQLite discrepancy: month {sql_month['month']} {label} {key}: {actual[key]} vs {target}")
    return True

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january",required=True,type=Path)
    p.add_argument("--july",required=True,type=Path)
    p.add_argument("--expected",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args(argv)
    reference=json.loads(a.expected.read_text())
    result=[]
    for month,path in ((1,a.january),(7,a.july)):
        actual=read_zip(path,month)
        expected=next(x for x in reference["months"] if x["month"]==month)
        compare(actual,expected)
        result.append({
          "month":month,
          "source_sha256":actual["source_sha256"],
          "verdict":"INDEPENDENT_SQL_SEGMENT_CAUSE_PARITY_PASS",
          "groups":actual["groups"]
        })
    summary={
       "status":"INDEPENDENT_SQL_SEGMENT_CAUSE_PARITY_PASS",
       "method":"Independent SQLite eligible/late/cause aggregation; no primary profile helpers",
       "limitations":"Observational, reported cause categories; not causal or mix-adjusted",
       "months":result
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":summary["status"],
          "months":[{"month":x["month"],"groups":x["groups"]} for x in result]},indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
