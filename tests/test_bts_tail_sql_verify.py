"""Synthetic SQL window and independent-arrival reconstruction checks."""
from datetime import datetime, timezone, timedelta
import pytest
import sqlite3
from fleet_tracker.bts_tail_sql_verify import validate_gate, pair_measures, compare

Z={"SEA":"America/Los_Angeles","ATL":"America/New_York",
   "JFK":"America/New_York"}
def record(**changes):
    row=dict(FlightDate="2025-01-01", Tail_Number="N123DL",
             Origin="SEA", Dest="ATL", CRSDepTime="2200", CRSArrTime="0700",
             DepTime="2200", ArrTime="0700", DepDelay="0.00", ArrDelay="0.00",
             CRSElapsedTime="360",ActualElapsedTime="360")
    row.update(changes)
    return row

def test_actual_elapsed_reconstructs_overnight_arrival_independently():
    leg, reason=validate_gate(record(),Z)
    assert reason=="valid"
    assert datetime.fromtimestamp(leg[3]*60,timezone.utc).isoformat()=="2025-01-02T06:00:00+00:00"
    assert datetime.fromtimestamp(leg[4]*60,timezone.utc).isoformat()=="2025-01-02T12:00:00+00:00"

def test_arrival_delay_elapsed_disagreement_rejected():
    leg, reason=validate_gate(record(ArrDelay="27", ActualElapsedTime="360", ArrTime="0700"),Z)
    assert leg is None and reason=="arrival_delay_elapsed_mismatch"

def test_unknown_iata_zone_fails_closed():
    leg,reason=validate_gate(record(Dest="ZZZ"),Z)
    assert leg is None and reason=="missing_airport_zone"

def test_sql_lead_pairing_and_delay_quadrants():
    db=sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE valid_legs(
      id INTEGER PRIMARY KEY, tail TEXT, origin TEXT, dest TEXT,
      dep_epoch INTEGER, arr_epoch INTEGER, dep_delay REAL, arr_delay REAL)""")
    db.executemany("""INSERT INTO valid_legs(tail,origin,dest,dep_epoch,arr_epoch,dep_delay,arr_delay)
      VALUES(?,?,?,?,?,?,?)""",[
      ("N1","SEA","ATL",100,160,0,20),
      ("N1","ATL","JFK",220,280,18,0),
      ("N2","SEA","ATL",200,260,0,0),
      ("N2","ATL","JFK",320,390,0,0),
      ("N3","ATL","JFK",100,180,0,0),
      ("N3","SEA","ATL",240,300,0,0),
    ])
    summary=pair_measures(db)
    assert summary["observed_consecutive_pairs"]==3
    assert summary["airport_discontinuities"]==1
    assert summary["candidate_20_to_360_min"]==2
    assert summary["candidate_median_ground_minutes"]==60
    quadrants=summary["descriptive_delay_association"]
    assert quadrants["previous_arrival_late_15"]==1
    assert quadrants["previous_arrival_not_late_15"]==1
    assert quadrants["next_departure_late_after_late_arrival"]==1
    assert quadrants["next_departure_late_after_not_late_arrival"]==0
    db.close()

def test_exact_reconciliation_rejects_wrong_pair_count():
    a={"source_sha256":"abc","scheduled_dl":2,"complete_nondiverted":2,
       "valid_timestamped_legs":2,"invalid_status":0,"excluded_canceled_or_diverted":0,
       "rejection_reasons":{},"pairs":{"candidate_20_to_360_min":1}}
    b={**a,"pairs":{"candidate_20_to_360_min":2}}
    with pytest.raises(AssertionError,match="pair discrepancy"):
        compare(a,b)
