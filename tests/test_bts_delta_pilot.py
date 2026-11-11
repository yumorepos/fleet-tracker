"""No network access or original BTS data required for unit tests."""
import csv
import io
import zipfile
import pytest
from fleet_tracker.bts_delta_pilot import analyze, columns

HEADER = ["FlightDate","Reporting_Airline","Flight_Number_Reporting_Airline","Origin","Dest",
          "CRSDepTime","CRSArrTime","Tail_Number","Cancelled","Diverted","ArrDel15","ArrDelay"]

def record(**changes):
    d=dict(zip(HEADER,["2025-01-02","DL","123","ATL","JFK","0800","1030","N123DL","0","0","0","-2"]))
    d.update(changes)
    return d

def archive(tmp_path, rows):
    buffer=io.StringIO()
    writer=csv.DictWriter(buffer, fieldnames=HEADER)
    writer.writeheader()
    writer.writerows(rows)
    path=tmp_path/"source.zip"
    with zipfile.ZipFile(path,"w") as z:
        z.writestr("official.csv",buffer.getvalue())
    return path

def test_schema_requires_all_fields():
    assert columns(HEADER)["carrier"]=="Reporting_Airline"
    with pytest.raises(ValueError, match="Missing required"):
        columns(["FlightDate"])

def test_kpis_use_correct_denominators(tmp_path):
    rows=[record(),record(Flight_Number_Reporting_Airline="124",ArrDel15="1",ArrDelay="16"),
          record(Flight_Number_Reporting_Airline="125",Cancelled="1",ArrDel15="",ArrDelay=""),
          record(Flight_Number_Reporting_Airline="126",Diverted="1",ArrDel15="",ArrDelay=""),
          record(Flight_Number_Reporting_Airline="127",ArrDel15="",ArrDelay=""),
          record(Reporting_Airline="UA")]
    r=analyze(archive(tmp_path,rows),1)
    assert r["counts"]["all"]==6 and r["counts"]["dl"]==5
    assert r["counts"]["eligible"]==3
    assert r["arrival_ontime_denominator"]==2
    assert r["arrival_ontime_rate_completed_valid"]==.5
    assert r["cancellation_rate_scheduled"]==.2
    assert r["diversion_rate_scheduled"]==.2
    assert r["core_kpi_gate"]=="REVISE"

def test_duplicate_keys_and_delay_disagreement_flagged(tmp_path):
    row=record(ArrDel15="0",ArrDelay="45")
    r=analyze(archive(tmp_path,[row,row]),1)
    assert r["counts"]["duplicates"]==1
    assert r["counts"]["flag_conflicts"]==2

def test_wrong_source_month_fails(tmp_path):
    with pytest.raises(ValueError, match="Wrong month"):
        analyze(archive(tmp_path,[record(FlightDate="2025-07-02")]),1)

def test_only_approved_months(tmp_path):
    with pytest.raises(ValueError, match="Only Jan"):
        analyze(archive(tmp_path,[record()]),2)

def test_excel_formatted_binary_flags(tmp_path):
    r=analyze(archive(tmp_path,[record(Cancelled="0.00", Diverted="0.00",
                                       ArrDel15="0.00", ArrDelay="-2.00")]),1)
    assert r["counts"]["status_valid"]==1
    assert r["counts"]["eligible"]==1
    assert r["counts"]["arr15_valid"]==1
    assert r["counts"]["ontime"]==1
