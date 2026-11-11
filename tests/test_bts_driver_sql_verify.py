"""Independent SQL aggregation tests do not import the primary profiler."""
from fleet_tracker.bts_driver_sql_verify import (
  binary,number,new_db,insert_rows,import_row,grouped,compare
)
import pytest

def source_row(origin="ATL",cancel="0.00",divert="0.00",flag="1.00",
               delay="20.00",lateaircraft="15.00"):
    return {
      "Origin":origin,"Cancelled":cancel,"Diverted":divert,"ArrDel15":flag,
      "ArrDelay":delay,"CarrierDelay":"5.00","WeatherDelay":"0.00",
      "NASDelay":"0.00","SecurityDelay":"0.00","LateAircraftDelay":lateaircraft
    }

def test_numeric_flag_contract_and_missingness():
    assert binary("0.00")==0 and binary("1.00")==1
    assert binary("") is None and binary("2.00") is None
    assert number("inf") is None

def test_sql_groups_and_eligibility():
    db=new_db()
    insert_rows(db,[
      import_row(source_row()),
      import_row(source_row(origin="JFK",flag="0.00",delay="-5",lateaircraft="")),
      import_row(source_row(origin="ATL",cancel="1.00",flag="",delay="",lateaircraft="")),
    ])
    g=grouped(db)
    db.close()
    assert g["ALL_DL"]["scheduled"]==3
    assert g["ATL_origin"]["scheduled"]==2
    assert g["Other_origin"]["scheduled"]==1
    assert g["ALL_DL"]["canceled"]==1
    assert g["ALL_DL"]["completed"]==2
    assert g["ALL_DL"]["on_time"]==1
    assert g["ALL_DL"]["late_arrival_15"]==1
    assert g["ATL_origin"]["positive_lateaircraft"]==1
    assert g["ATL_origin"]["lateaircraft_minutes"]==15
    assert g["ALL_DL"]["mismatch_cause_sum"]==0

def test_sql_unreported_cause_is_missing_not_zero():
    db=new_db()
    insert_rows(db,[import_row(source_row(lateaircraft=""))])
    x=grouped(db)["ALL_DL"]
    db.close()
    assert x["complete"]==0 and x["missing_causes"]==1
    assert x["positive_lateaircraft"]==0

def test_sql_detects_cause_sum_mismatch():
    db=new_db()
    insert_rows(db,[import_row(source_row(delay="25.00"))])
    x=grouped(db)["ALL_DL"]
    db.close()
    assert x["mismatch_cause_sum"]==1

def test_reference_comparison_fails_on_mismatched_origin_count():
    db=new_db()
    insert_rows(db,[import_row(source_row())])
    actual={"source_sha256":"abc","month":1,"groups":grouped(db)}
    db.close()
    ref={"source_sha256":"abc","groups":{}}
    with pytest.raises(AssertionError,match="Missing reference"):
        compare(actual,ref)
