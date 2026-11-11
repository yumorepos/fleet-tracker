"""Synthetic, table-grain and attribution-denominator regression checks."""
from collections import Counter
import pytest
from fleet_tracker.bts_driver_profile import process, finalize, segment, number

def row(**kw):
    data=dict(
      Origin="ATL",Cancelled="0.00",Diverted="0.00",
      ArrDel15="1.00",ArrDelay="30.00",
      CarrierDelay="5.00",WeatherDelay="0.00",NASDelay="5.00",
      SecurityDelay="0.00",LateAircraftDelay="20.00")
    data.update(kw)
    return data

def test_segment_is_strict_atl_origin_only():
    assert segment("ATL")=="ATL_origin"
    assert segment("JFK")=="Other_origin"
    assert segment(" atl ")=="ATL_origin"

def test_numeric_preserves_missing_as_unknown():
    assert number("") is None
    assert number("12.00")==12
    assert number("inf") is None

def test_delayed_arrival_causes_counted_without_double_counting_flights():
    c=Counter()
    process(row(),c)
    x=finalize(c)
    assert x["scheduled"]==1
    assert x["late_arrival_15"]==1
    assert x["reported_cause_minutes"]["LateAircraftDelay"]==20
    assert x["reported_positive_cause_flight_count"]["LateAircraftDelay"]==1
    assert x["late_aircraft_reported_positive_share_of_late_arrivals"]==1
    assert x["cause_detail_coverage_among_late_arrivals"]==1

def test_early_arrival_cause_fields_blank_are_not_invalid():
    c=Counter()
    process(row(ArrDel15="0.00",ArrDelay="-5.00",
      CarrierDelay="",WeatherDelay="",NASDelay="",
      SecurityDelay="",LateAircraftDelay=""),c)
    x=finalize(c)
    assert x["on_time"]==1
    assert x["late_arrival_15"]==0
    assert x["late_aircraft_reported_positive_share_of_late_arrivals"] is None

def test_missing_delay_cause_not_treated_as_reported_zero():
    c=Counter()
    process(row(LateAircraftDelay=""),c)
    x=finalize(c)
    assert x["late_arrivals_missing_cause_detail"]==1
    assert x["late_arrivals_with_complete_cause_detail"]==0
    assert x["reported_cause_minutes"]["LateAircraftDelay"]==0
    assert x["cause_detail_coverage_among_late_arrivals"]==0

def test_cancelled_excluded_from_arrival_population():
    c=Counter()
    process(row(Cancelled="1.00",ArrDel15="",ArrDelay="",LateAircraftDelay=""),c)
    x=finalize(c)
    assert x["scheduled"]==1 and x["canceled"]==1
    assert x["completed"]==0 and x["late_arrival_15"]==0

def test_invalid_arrival_flag_not_reassigned_to_ontime():
    c=Counter()
    process(row(ArrDel15=""),c)
    x=finalize(c)
    assert x["bad_arrival_flag"]==1
    assert x["on_time"]==0

def test_late_aircraft_not_equated_to_all_late_arrivals():
    c=Counter()
    process(row(LateAircraftDelay="0.00",CarrierDelay="25.00"),c)
    x=finalize(c)
    assert x["late_arrival_15"]==1
    assert x["reported_positive_cause_flight_count"]["LateAircraftDelay"]==0
