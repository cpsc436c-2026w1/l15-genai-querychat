"""Scorers against hand-made answers: every gate passes and fails where it should. No model calls."""

import json

import pytest

from evals.correctness.build_questions import load
from evals.correctness.checks import judge, parse_answer, sql_guard

QS = {q["id"]: q for q in load()}


def ans(sql, unit="trips", interpretation="as asked", confidence="high"):
    return json.dumps(dict(sql=sql, unit=unit, interpretation=interpretation, confidence=confidence))


@pytest.mark.parametrize("qid", list(QS))
def test_reference_sql_passes_its_own_question(qid):
    q = QS[qid]
    v = judge(ans(q["sql"]), q)
    assert v.outcome == "pass", v.to_dict()


def test_equivalent_sql_passes():
    # JFK by zone id instead of a join; percent written as a fraction
    assert judge(ans("SELECT COUNT(*) AS n FROM taxi WHERE PULocationID = 132"), QS["q09"]).outcome == "pass"
    frac = "SELECT AVG(CASE WHEN payment_type = 2 THEN 1 ELSE 0 END) AS share FROM taxi"
    assert judge(ans(frac, unit="fraction"), QS["q08"]).outcome == "pass"


def test_schema_failures():
    assert judge("The answer is 42", QS["q01"]).outcome == "schema failure"
    assert judge(json.dumps({"sql": "SELECT 1"}), QS["q01"]).outcome == "schema failure"         # fields missing
    assert judge(ans("SELECT 1", confidence="very"), QS["q01"]).outcome == "schema failure"       # not in enum
    extra = json.dumps(dict(sql="SELECT 1", unit="x", interpretation="y", confidence="low", value=3))
    assert judge(extra, QS["q01"]).outcome == "schema failure"                                     # extra field
    a, err = parse_answer("```json\n" + ans("SELECT COUNT(*) FROM taxi") + "\n```")
    assert a is not None and err is None                                                            # fence tolerated


def test_sql_errors():
    assert judge(ans("SELECT COUNT(*) FROM trips"), QS["q01"]).outcome == "SQL error"              # no such table
    assert judge(ans("SELECT AVG(tip) FROM taxi"), QS["q04"]).outcome == "SQL error"               # no such column
    assert judge(ans("DROP TABLE taxi"), QS["q01"]).outcome == "SQL error"                         # refused
    assert judge(ans("SELECT 1; SELECT 2"), QS["q01"]).outcome == "SQL error"                      # two statements
    assert sql_guard("SELECT 'a;b' AS s") is None                                                   # ; inside a string
    assert judge(ans("SELECT * FROM read_csv('/etc/passwd')"), QS["q01"]).outcome == "SQL error"   # no file access


def test_value_mismatches():
    # off by the 18 trips outside January: a count must be exact
    jan = ("SELECT COUNT(*) FROM taxi WHERE tpep_pickup_datetime >= TIMESTAMP '2024-01-01' "
           "AND tpep_pickup_datetime < TIMESTAMP '2024-02-01'")
    assert judge(ans(jan), QS["q01"]).outcome == "value mismatch"
    # mean of per-trip ratios instead of ratio of sums
    mor = "SELECT 100 * AVG(tip_amount / fare_amount) FROM taxi WHERE payment_type = 1 AND fare_amount > 0"
    assert judge(ans(mor, unit="percent"), QS["q11"]).outcome == "value mismatch"
    # cash as payment_type 1
    assert judge(ans("SELECT COUNT(*) FROM taxi WHERE payment_type = 1"), QS["q03"]).outcome == "value mismatch"
    assert judge(ans("SELECT 'many' AS n"), QS["q01"]).outcome == "value mismatch"                 # not a number
    assert judge(ans("SELECT 1 AS n WHERE false"), QS["q01"]).outcome == "value mismatch"          # no rows


def test_ambiguous_question_reports_the_other_reading():
    v = judge(ans("SELECT AVG(trip_distance) FROM taxi", unit="miles"), QS["q12"])
    assert v.outcome == "value mismatch"
    assert "other reading" in v.value_note


def test_tolerance_edges():
    ref = QS["q02"]["reference_value"]
    assert judge(ans(f"SELECT {ref * 1.009} AS x", unit="miles"), QS["q02"]).outcome == "pass"
    assert judge(ans(f"SELECT {ref * 1.011} AS x", unit="miles"), QS["q02"]).outcome == "value mismatch"
