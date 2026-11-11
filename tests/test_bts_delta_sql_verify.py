"""No network or real flight records; verify independent SQL recomputation."""
import csv
import io
import zipfile
import pytest
from fleet_tracker.bts_delta_sql_verify import aggregate, verify

FIELDS=["FlightDate","Reporting_Airline","Flight_Number_Reporting_Airline",
        "Origin","Dest","CRSDepTime","Cancelled","Diverted","ArrDel15","ArrDelay","Tail_Number"]

def source(tmp_path):
    s=io.StringIO()
    writer=csv.DictWriter(s,fieldnames=FIELDS)
    writer.writeheader()
    rows=[
        ["2025-01-01","DL","1","ATL","JFK","0800","0.00","0.00","0.00","-2.00","N123"],
        ["2025-01-02","DL","2","ATL","JFK","0800","1.00","0.00","","",""],
        ["2025-01-03","DL","3","ATL","JFK","0800","0.00","1.00","","",""],
        ["2025-01-04","DL","4","ATL","JFK","0800","0.00","0.00","1.00","20","N123"],
        ["2025-01-05","UA","5","SFO","JFK","0900","0.00","0.00","1.00","22","N999"],
    ]
    for row in rows:
        writer.writerow(dict(zip(FIELDS,row)))
    p=tmp_path/"source.zip"
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("official.csv",s.getvalue())
    return p

def test_sql_denominators_and_filtered_carrier(tmp_path):
    r=aggregate(source(tmp_path))
    assert r["dl"]==4 and r["canceled"]==1 and r["diverted"]==1
    assert r["eligible"]==2 and r["arr15_valid"]==2
    assert r["ontime"]==1 and r["tail_present"]==2
    assert r["duplicates"]==0

def test_fails_on_wrong_primary_number(tmp_path):
    file=source(tmp_path)
    original=aggregate(file)
    report={"months":[{"month":1,"source_zip_sha256":original["sha256"],
                        "counts":{**original,"ontime":999,"missing_clock":0},
                        "distinct_flight_dates":original["days"]}]}
    with pytest.raises(ValueError,match="disagreed"):
        verify(1,file,report)
