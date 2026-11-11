"""Bounded read-only BTS DL origin-segment and reported-delay-cause study.

Exploratory source exercise, not weather causality, operational prediction, or
complete tail activity. Only aggregate results are persisted.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fleet_tracker.bts_delta_pilot import flight_date, flag, URL

EXPECTED_SHA = {
    1: "868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf",
    7: "74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19",
}
CAUSE_FIELDS = (
    "CarrierDelay","WeatherDelay","NASDelay","SecurityDelay","LateAircraftDelay"
)
REQUIRED = (
    "FlightDate","Reporting_Airline","Origin","Cancelled","Diverted",
    "ArrDel15","ArrDelay",*CAUSE_FIELDS
)

def number(raw):
    try:
        x=Decimal(str(raw or "").strip())
    except InvalidOperation:
        return None
    return float(x) if x.is_finite() else None

def segment(origin):
    return "ATL_origin" if str(origin).strip().upper()=="ATL" else "Other_origin"

def empty():
    return Counter()

def process(row, c:Counter):
    c["scheduled"] += 1
    canceled, diverted = flag(row["Cancelled"]), flag(row["Diverted"])
    if canceled is None or diverted is None:
        c["bad_status"] += 1
        return
    c["canceled"] += canceled
    c["diverted"] += diverted
    if canceled or diverted:
        c["excluded_canceled_or_diverted"] += 1
        return
    c["completed"] += 1
    arrival = flag(row["ArrDel15"])
    arrdelay = number(row["ArrDelay"])
    if arrival is None:
        c["bad_arrival_flag"] += 1
        return
    c["valid_arrival_flags"] += 1
    c["on_time"] += 1 - arrival
    c["late_arrival_15"] += arrival
    if arrdelay is None or (arrdelay>=15)!=bool(arrival):
        c["arrival_delay_discrepancy"] += 1
        return
    if not arrival:
        return
    values = [number(row[k]) for k in CAUSE_FIELDS]
    if any(v is None or v<0 for v in values):
        c["late_arrivals_missing_cause_detail"] += 1
        return
    c["late_arrivals_with_complete_cause_detail"] += 1
    for name,value in zip(CAUSE_FIELDS,values):
        if value>0:
            c["positive_"+name] += 1
        # preserve the original numeric precision in a fixed-point integer
        c["cause_minutes_cents_"+name] += int(round(value*100))
    if abs(sum(values)-arrdelay)>1:
        c["cause_minutes_vs_arrdelay_over_1min"] += 1

def percent(a,b):
    return round(a/b,6) if b else None

def finalize(c):
    out = {k:int(c[k]) for k in (
        "scheduled","bad_status","canceled","diverted",
        "excluded_canceled_or_diverted","completed","bad_arrival_flag",
        "valid_arrival_flags","on_time","late_arrival_15",
        "arrival_delay_discrepancy",
        "late_arrivals_missing_cause_detail",
        "late_arrivals_with_complete_cause_detail",
        "cause_minutes_vs_arrdelay_over_1min"
    )}
    out["arrival_on_time_rate"]=percent(c["on_time"],c["valid_arrival_flags"])
    out["cancellation_rate"]=percent(c["canceled"],c["scheduled"])
    out["diversion_rate"]=percent(c["diverted"],c["scheduled"])
    out["cause_detail_coverage_among_late_arrivals"]=percent(
        c["late_arrivals_with_complete_cause_detail"],c["late_arrival_15"])
    out["reported_positive_cause_flight_count"]={
        k:int(c["positive_"+k]) for k in CAUSE_FIELDS
    }
    out["reported_cause_minutes"]={
        k:round(c["cause_minutes_cents_"+k]/100,2) for k in CAUSE_FIELDS
    }
    out["late_aircraft_reported_positive_share_of_late_arrivals"]=percent(
        c["positive_LateAircraftDelay"],c["late_arrival_15"])
    return out

def analyze(path:Path,month:int):
    if month not in EXPECTED_SHA:
        raise ValueError("Only 2025 Jan/Jul")
    if path.stat().st_size>150_000_000:
        raise ValueError("Source ZIP exceeds bounded pilot")
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):
            h.update(chunk)
    if h.hexdigest()!=EXPECTED_SHA[month]:
        raise ValueError("Source ZIP hash drift")
    groups={"ALL_DL":empty(),"ATL_origin":empty(),"Other_origin":empty()}
    with zipfile.ZipFile(path) as archive:
        items=[i for i in archive.infolist() if i.filename.lower().endswith(".csv") and not i.is_dir()]
        if len(items)!=1 or items[0].file_size>1_000_000_000:
            raise ValueError("Expected one bounded source CSV")
        with archive.open(items[0]) as raw,io.TextIOWrapper(raw,encoding="utf-8-sig",newline="") as stream:
            reader=csv.DictReader(stream)
            if not set(REQUIRED).issubset(set(reader.fieldnames or ())):
                raise ValueError("Required BTS delay cause columns not available in source ZIP: "+
                    ",".join(sorted(set(REQUIRED)-set(reader.fieldnames or ()))))
            for row in reader:
                if (row["Reporting_Airline"] or "").strip()!="DL":
                    continue
                day=flight_date(row["FlightDate"])
                if (day.year,day.month)!=(2025,month):
                    raise ValueError("Unexpected source date")
                process(row,groups["ALL_DL"])
                process(row,groups[segment(row["Origin"])])
    out={k:finalize(v) for k,v in groups.items()}
    allrow, atl,other=(out[x] for x in ("ALL_DL","ATL_origin","Other_origin"))
    for count in ("scheduled","canceled","diverted","completed","on_time",
                  "late_arrival_15","late_arrivals_with_complete_cause_detail"):
        if allrow[count]!=atl[count]+other[count]:
            raise AssertionError("Segment group reconciliation failed: "+count)
    coverage=allrow["cause_detail_coverage_among_late_arrivals"]
    if (allrow["scheduled"]<1000 or allrow["bad_status"] or
        allrow["bad_arrival_flag"] or allrow["arrival_delay_discrepancy"] or
        coverage is None or coverage<.95):
        verdict="REVISE"
    else:
        verdict="GO_FOR_DESCRIPTIVE_CAUSE_AUDIT"
    return {"month":month,"year":2025,"source_sha256":h.hexdigest(),
            "cause_field_contract":"Carrier-reported delay-cause minutes on ARRDEL15=1 flights; no independent causal attribution",
            "verdict":verdict,"groups":out}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--january",required=True,type=Path)
    parser.add_argument("--july",required=True,type=Path)
    parser.add_argument("--baseline",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv)
    baseline=json.loads(args.baseline.read_text())
    months=[analyze(args.january,1),analyze(args.july,7)]
    for row in months:
        ref=next(x for x in baseline["months"] if x["month"]==row["month"])
        allc=row["groups"]["ALL_DL"]
        if (ref["source_zip_sha256"]!=row["source_sha256"]
            or ref["counts"]["dl"]!=allc["scheduled"]
            or ref["counts"]["eligible"]!=allc["completed"]
            or ref["counts"]["ontime"]!=allc["on_time"]):
            raise AssertionError("Original independently validated BTS KPI totals disagree")
    output={
        "research_question":"ATL-origin vs other DL reported domestic departures: arrival punctuality and carrier-reported delay cause attribution",
        "source_scope":"BTS 2025 Jan/Jul Reporting_Airline=DL, domestic reporting population",
        "limitations":[
            "Only two separate months; no traffic mix adjustment or causal identification",
            "ATL-origin comparison is descriptive, not an airport effect estimate",
            "BTS carrier-reported causes are not independent validation of physical same-tail delay transfer",
            "LateAircraftDelay is included in carrier-reported cause data on late arriving flights; missing detail is not zero",
            "No complete aircraft rotation, weather attribution independent of reporting, or real airline impact claim",
        ],
        "months":months
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"months":[{
        "month":m["month"],"verdict":m["verdict"],"groups":m["groups"]
    }for m in months]},indent=2))
    return 0 if all(m["verdict"]=="GO_FOR_DESCRIPTIVE_CAUSE_AUDIT" for m in months) else 2

if __name__=="__main__":
    raise SystemExit(main())
