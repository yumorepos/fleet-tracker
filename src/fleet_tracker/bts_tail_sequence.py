"""BTS DL 2025 tail-sequence feasibility: reported operations, not full fleet activity."""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import argparse
import csv
import hashlib
import io
import json
import math
import zipfile

from fleet_tracker.bts_delta_pilot import flag, flight_date

FIELDS = ("FlightDate","Reporting_Airline","Origin","Dest","Tail_Number",
          "CRSDepTime","CRSArrTime","DepTime","ArrTime","DepDelay","ArrDelay",
          "CRSElapsedTime","ActualElapsedTime","Cancelled","Diverted")
HASHES = {
    1:"868387dcedaef1b8d8392e608e642219fde50d594c3cf2094aec858167629ccf",
    7:"74309a3a734d5104b4c212390c06eb3acacff15124b9cea49ba7d69a609a0d19",
}

def numeric(raw):
    try:
        x=float(Decimal(str(raw).strip()))
        return x if math.isfinite(x) else None
    except (InvalidOperation,ValueError,OverflowError):
        return None

def clock(raw):
    n=numeric(raw)
    if n is None or not n.is_integer():
        return None
    x=int(n)
    if x==2400:
        return 1440
    hour,minute=divmod(x,100)
    return hour*60+minute if 0<=hour<24 and 0<=minute<60 else None

def matches(dt, value):
    expected=dt.hour*60+dt.minute
    delta=abs(expected-value%1440)
    return min(delta,1440-delta)<=1

@dataclass(frozen=True)
class Leg:
    tail:str
    origin:str
    dest:str
    dep:datetime
    arr:datetime
    dep_delay:float=0.0
    arr_delay:float=0.0

def timestamped(row,zones):
    tail=(row.get("Tail_Number") or "").strip().upper()
    if not tail:
        return None,"missing_tail"
    origin=(row.get("Origin") or "").strip().upper()
    dest=(row.get("Dest") or "").strip().upper()
    if origin not in zones or dest not in zones:
        return None,"missing_airport_zone"
    try:
        z1=ZoneInfo(zones[origin])
        z2=ZoneInfo(zones[dest])
    except (ZoneInfoNotFoundError,KeyError,TypeError):
        return None,"missing_airport_zone"
    depcrs,arrcrs,depclock,arrclock=(clock(row.get(k)) for k in
        ("CRSDepTime","CRSArrTime","DepTime","ArrTime"))
    if any(x is None for x in (depcrs,arrcrs,depclock,arrclock)):
        return None,"invalid_or_missing_gate_clock"
    depdelay,arrdelay,crsminutes,actualminutes=(numeric(row.get(k)) for k in
        ("DepDelay","ArrDelay","CRSElapsedTime","ActualElapsedTime"))
    if any(x is None for x in (depdelay,arrdelay,crsminutes,actualminutes)):
        return None,"missing_delay_or_elapsed"
    if not (0<crsminutes<=1200 and 0<actualminutes<=1200):
        return None,"implausible_elapsed"
    if not (-1440<=depdelay<=2880 and -1440<=arrdelay<=2880):
        return None,"extreme_reported_delay"
    try:
        day=flight_date(row["FlightDate"])
    except ValueError:
        return None,"invalid_flight_date"
    sched_local=datetime.combine(day,time.min)+timedelta(minutes=depcrs)
    sched_dep=sched_local.replace(tzinfo=z1).astimezone(timezone.utc)
    sched_arr=sched_dep+timedelta(minutes=crsminutes)
    if not matches(sched_arr.astimezone(z2),arrcrs):
        return None,"scheduled_arrival_local_clock_mismatch"
    dep=sched_dep+timedelta(minutes=depdelay)
    arr=sched_arr+timedelta(minutes=arrdelay)
    if not matches(dep.astimezone(z1),depclock):
        return None,"actual_departure_local_clock_mismatch"
    if not matches(arr.astimezone(z2),arrclock):
        return None,"actual_arrival_local_clock_mismatch"
    if (arr-dep).total_seconds()<=0 or abs((arr-dep).total_seconds()/60-actualminutes)>1:
        return None,"elapsed_minutes_mismatch"
    return Leg(tail,origin,dest,dep,arr,depdelay,arrdelay),"valid"

def count_pairs(legs):
    grouped=defaultdict(list)
    for leg in legs:
        grouped[leg.tail].append(leg)
    c=Counter()
    gaps=[]
    for entries in grouped.values():
        entries.sort(key=lambda x:x.dep)
        for old,new in zip(entries,entries[1:]):
            c["observed_consecutive_pairs"]+=1
            if old.dest!=new.origin:
                c["airport_discontinuities"]+=1
                continue
            c["airport_continuity"]+=1
            gap=(new.dep-old.arr).total_seconds()/60
            if gap<0:
                c["same_tail_overlap"]+=1
            elif gap<20:
                c["gap_under_20_min"]+=1
            elif gap<=360:
                c["candidate_20_to_360_min"]+=1
                gaps.append(gap)
                # Descriptive exposure/outcome association within selected
                # matching-tail observations only. This is NOT causal.
                group="late_inbound" if old.arr_delay>=15 else "not_late_inbound"
                c["candidates_"+group]+=1
                if new.dep_delay>=15:
                    c["next_departure_late_"+group]+=1
                band=("20_to_59" if gap<60 else
                      "60_to_119" if gap<120 else "120_to_360")
                c["candidates_"+band+"_"+group]+=1
                if new.dep_delay>=15:
                    c["next_late_"+band+"_"+group]+=1
            elif gap<=1440:
                c["gap_6_to_24h"]+=1
            else:
                c["gap_over_24h"]+=1
    result={k:c[k] for k in ("observed_consecutive_pairs","airport_discontinuities",
            "airport_continuity","same_tail_overlap","gap_under_20_min",
            "candidate_20_to_360_min","gap_6_to_24h","gap_over_24h")}
    late=c["candidates_late_inbound"]
    early=c["candidates_not_late_inbound"]
    assert late+early==result["candidate_20_to_360_min"]
    def rate(n,d):
        return round(n/d,6) if d else None
    association={
        "previous_arrival_late_15":late,
        "previous_arrival_not_late_15":early,
        "next_departure_late_after_late_arrival":c["next_departure_late_late_inbound"],
        "next_departure_late_after_not_late_arrival":c["next_departure_late_not_late_inbound"],
        "next_late_rate_after_late_arrival":rate(c["next_departure_late_late_inbound"],late),
        "next_late_rate_after_not_late_arrival":rate(c["next_departure_late_not_late_inbound"],early),
        "actual_ground_gap_bands":{
            band:{
                group:{
                    "candidate_connections":c["candidates_"+band+"_"+group],
                    "next_departure_late":c["next_late_"+band+"_"+group],
                    "rate":rate(c["next_late_"+band+"_"+group],
                                c["candidates_"+band+"_"+group])
                } for group in ("late_inbound","not_late_inbound")
            } for band in ("20_to_59","60_to_119","120_to_360")
        },
    }
    result["descriptive_delay_association"]=association
    result["unique_valid_tails"]=len(grouped)
    result["tails_with_2plus_valid_legs"]=sum(len(x)>=2 for x in grouped.values())
    result["candidate_median_ground_minutes"]=round(median(gaps),1) if gaps else None
    return result

def evaluate(path,month,zones):
    if month not in HASHES:
        raise ValueError("Only January and July 2025")
    digest=hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda:src.read(1024*1024),b""):
            digest.update(chunk)
    if digest.hexdigest()!=HASHES[month]:
        raise ValueError("Official source ZIP hash has changed; review before using")
    c=Counter()
    reasons=Counter()
    unknown=Counter()
    legs=[]
    with zipfile.ZipFile(path) as archive:
        files=[f for f in archive.infolist() if f.filename.lower().endswith(".csv") and not f.is_dir()]
        if len(files)!=1 or files[0].file_size>1_000_000_000:
            raise ValueError("Expected one bounded BTS CSV")
        with archive.open(files[0]) as fh,io.TextIOWrapper(fh,encoding="utf-8-sig",newline="") as text:
            reader=csv.DictReader(text)
            if not set(FIELDS).issubset(set(reader.fieldnames or [])):
                raise ValueError("Flight timestamp source columns unavailable")
            for row in reader:
                if (row["Reporting_Airline"] or "").strip()!="DL":
                    continue
                c["scheduled"]+=1
                canceled,diverted=flag(row["Cancelled"]),flag(row["Diverted"])
                if canceled is None or diverted is None:
                    c["invalid_status"]+=1
                    continue
                if canceled or diverted:
                    c["not_completed"]+=1
                    continue
                c["completed"]+=1
                leg,reason=timestamped(row,zones)
                if leg is None:
                    reasons[reason]+=1
                    if reason=="missing_airport_zone":
                        for key in ("Origin","Dest"):
                            if row[key] not in zones:
                                unknown[row[key]]+=1
                else:
                    legs.append(leg)
    pairs=count_pairs(legs)
    n=c["completed"]
    comparable=pairs["airport_continuity"]
    cover=round(len(legs)/n,6) if n else None
    return {
        "year":2025,"month":month,"source_sha256":digest.hexdigest(),
        "scheduled_dl":c["scheduled"],"complete_nondiverted":n,
        "valid_timestamped_legs":len(legs),"timestamp_valid_share":cover,
        "invalid_status":c["invalid_status"],"excluded_canceled_or_diverted":c["not_completed"],
        "rejection_reasons":dict(reasons),
        "unknown_airports_top10":unknown.most_common(10),
        "pairs":pairs,
        "timestamp_gate":"GO" if n>=1000 and cover is not None and cover>=.98 else "REVISE",
        "candidate_gate":"CANDIDATE_ONLY" if
            pairs["candidate_20_to_360_min"]>=500 and comparable>0
            and pairs["same_tail_overlap"]/comparable<=.005 else "REVISE",
    }

def apply_2025_airport_zone_aliases(reference_zones: dict) -> dict:
    """One source-backed historical-code correction; not a general IATA remapper.

    BTS 2025 uses PBI (West Palm Beach). The airport's own notice describes
    its 2026 change to DJT; FAA/AirNav confirms Eastern time at this site.
    Only used for this frozen 2025 Jan/Jul research scope.
    """
    zones = dict(reference_zones)
    if zones.get("PBI") not in (None, "America/New_York"):
        raise ValueError("Conflicting PBI historical zone: independent audit needed")
    zones["PBI"] = "America/New_York"
    return zones


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--january",type=Path,required=True)
    p.add_argument("--july",type=Path,required=True)
    p.add_argument("--prior-report",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    import airportsdata
    zones=apply_2025_airport_zone_aliases(
        {k:v["tz"] for k,v in airportsdata.load("IATA").items() if v.get("tz")}
    )
    prior=json.loads(args.prior_report.read_text())
    months=[evaluate(args.january,1,zones),evaluate(args.july,7,zones)]
    for m in months:
        baseline=next((x for x in prior["months"] if x["month"]==m["month"]),None)
        if baseline is None or (m["source_sha256"]!=baseline["source_zip_sha256"] or
            m["scheduled_dl"]!=baseline["counts"]["dl"] or
            m["complete_nondiverted"]!=baseline["counts"]["eligible"]):
            raise ValueError("Source/counts disagree with independently validated primary pilot")
    report={
        "study":"Delta reporting-carrier Jan/Jul 2025 — observed tail-pair feasibility",
        "airport_zone_reference":"airportsdata==20261103 (MIT); IANA time-zone names",
        "scope":"Domestic reportable completed nondiverted flights; no international aircraft legs",
        "clock_validation":"Compare scheduled and actual gate clocks and actual elapsed minutes to UTC reconstruction",
        "candidate_definition":"Consecutive observed same tail, matching airport, 20-360 min nonoverlapping gate gap",
        "limits":"No full fleet utilization, certified turnarounds, causal propagation or unreported leg recovery",
        "delay_association_note":"P(next departure delay>=15 | prior observed arrival delay>=15) vs prior <15, selected 20-360min candidate pairs; noncausal and subject to selection, airport, weather, routing, schedule confounding",
        "months":months,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"months":[{"month":m["month"],"timestamp_gate":m["timestamp_gate"],
        "valid":m["valid_timestamped_legs"],"candidate_pairs":m["pairs"]["candidate_20_to_360_min"],
        "candidate_gate":m["candidate_gate"]} for m in months]},indent=2))
    return 0 if all(m["timestamp_gate"]=="GO" for m in months) else 2

if __name__=="__main__":
    raise SystemExit(main())
