"""Synthetic checks: local clocks, overnight timestamps and conservative links."""
from datetime import datetime,timedelta,timezone
from fleet_tracker.bts_tail_sequence import timestamped,count_pairs,clock,Leg

Z={"SEA":"America/Los_Angeles","ATL":"America/New_York",
   "JFK":"America/New_York"}
def flight(**edits):
    d=dict(FlightDate="2025-01-01",Tail_Number="N123DL",Origin="SEA",
        Dest="ATL",CRSDepTime="2200",CRSArrTime="0700",CRSElapsedTime="360",
        DepTime="2200",ArrTime="0700",DepDelay="0.00",ArrDelay="0.00",
        ActualElapsedTime="360")
    d.update(edits)
    return d

def test_overnight_two_timezones():
    leg,reason=timestamped(flight(),Z)
    assert reason=="valid"
    assert leg.dep.isoformat()=="2025-01-02T06:00:00+00:00"
    assert leg.arr.isoformat()=="2025-01-02T12:00:00+00:00"

def test_independent_departure_and_arrival_delay():
    leg,reason=timestamped(flight(DepDelay="10.00",DepTime="2210",ArrDelay="25.00",
                                  ArrTime="0725",ActualElapsedTime="375"),Z)
    assert reason=="valid" and leg is not None

def test_bad_arrival_local_clock_rejected():
    leg,reason=timestamped(flight(ArrTime="0845"),Z)
    assert leg is None and reason=="actual_arrival_local_clock_mismatch"

def test_bad_elapsed_rejected():
    leg,reason=timestamped(flight(ActualElapsedTime="190"),Z)
    assert leg is None and reason=="elapsed_minutes_mismatch"

def test_no_implicit_timezone_guessing():
    leg,reason=timestamped(flight(Dest="XXX"),Z)
    assert leg is None and reason=="missing_airport_zone"

def test_bts_2400_and_invalid_clock():
    assert clock("2400.00")==1440
    assert clock("2360.00") is None

def test_cross_midnight_same_airport_70_minute_gap():
    prev,_=timestamped(flight(),Z)
    nxt,reason=timestamped(flight(FlightDate="2025-01-02",Origin="ATL",Dest="JFK",
        CRSDepTime="0810",CRSArrTime="1010",CRSElapsedTime="120",
        DepTime="0810",ArrTime="1010",ActualElapsedTime="120"),Z)
    assert reason=="valid"
    summary=count_pairs([nxt,prev])
    assert summary["candidate_20_to_360_min"]==1
    assert summary["candidate_median_ground_minutes"]==70

def test_mismatched_airport_not_turn():
    d=datetime(2025,1,2,6,tzinfo=timezone.utc)
    a=Leg("N1","SEA","JFK",d,d+timedelta(hours=2))
    b=Leg("N1","ATL","SEA",d+timedelta(hours=4),d+timedelta(hours=7))
    s=count_pairs([a,b])
    assert s["airport_discontinuities"]==1 and s["candidate_20_to_360_min"]==0

def test_overlap_is_suspicious_not_a_turn():
    d=datetime(2025,1,2,6,tzinfo=timezone.utc)
    a=Leg("N1","ATL","JFK",d,d+timedelta(hours=2))
    b=Leg("N1","JFK","ATL",d+timedelta(hours=1),d+timedelta(hours=4))
    s=count_pairs([a,b])
    assert s["same_tail_overlap"]==1 and s["candidate_20_to_360_min"]==0

def test_no_inferred_activity_from_single_observation():
    d=datetime(2025,1,2,6,tzinfo=timezone.utc)
    s=count_pairs([Leg("N1","SEA","JFK",d,d+timedelta(hours=2))])
    assert s["observed_consecutive_pairs"]==0 and s["unique_valid_tails"]==1
