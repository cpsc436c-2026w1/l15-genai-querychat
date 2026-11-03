"""System prompt and answer schema.

The prompt follows querychat's structure (querychat/prompts/prompt.md: role, <tables> with the schema
querychat's format_schema prints, <data_description>, the SQL query guidelines, important guidelines).
What differs: there are no tools. The model answers once, through a JSON schema, and the eval harness runs
the SQL it wrote; the number scored is the one DuckDB returns, never one the model typed."""

from __future__ import annotations

import json
import re
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness.db import connect

CATEGORICAL_THRESHOLD = 20  # querychat's default: text columns with <= 20 distinct values list them


class Answer(BaseModel):
    """An answer to a question about the taxi data: the SQL that computes it and how to read the result."""

    # The class docstring and the field descriptions go to the model inside the JSON schema.

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(description="One DuckDB SELECT statement, no trailing semicolon, that returns exactly one row "
                                 "with one column holding the answer")
    unit: str = Field(description="Unit of the number the query returns, e.g. trips, miles, minutes, USD, percent")
    interpretation: str = Field(description="One sentence: how you read the question, including any assumption")
    confidence: Literal["low", "medium", "high"] = Field(description="How sure you are that the query answers the "
                                                                     "question as asked")


def answer_json_schema() -> dict:
    s = Answer.model_json_schema()
    s.pop("title", None)
    s["additionalProperties"] = False
    s["required"] = list(s["properties"])  # strict mode wants every field required
    for p in s["properties"].values():
        p.pop("title", None)
    return s


def parse_answer(text: str) -> tuple[Answer | None, str | None]:
    """Schema gate. Tolerates a ```json fence around the object (some models add one in JSON mode)."""
    t = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        return None, f"not JSON: {e.msg} at char {e.pos}"
    try:
        return Answer.model_validate(data), None
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, x['loc'])) or '(root)'}: {x['msg']}" for x in e.errors())
        return None, f"schema: {errs}"


DATA_DESCRIPTION = """\
NYC yellow taxi trip records that NYC TLC published for January 2024, one row per trip, and the TLC zone lookup.

taxi columns:
- VendorID: 1 = Creative Mobile Technologies, 2 = Curb Mobility, 6 = Myle Technologies
- tpep_pickup_datetime, tpep_dropoff_datetime: when the meter was engaged and disengaged (local time)
- passenger_count: number of passengers, entered by the driver (may be missing)
- trip_distance: trip distance in miles reported by the taximeter
- RatecodeID: 1 = Standard, 2 = JFK, 3 = Newark, 4 = Nassau or Westchester, 5 = Negotiated fare, 6 = Group ride, 99 = unknown
- store_and_fwd_flag: Y = trip record held in vehicle memory before sending, N = not
- PULocationID, DOLocationID: TLC taxi zone of pickup and dropoff; join to zones.LocationID
- payment_type: 0 = Flex Fare trip, 1 = Credit card, 2 = Cash, 3 = No charge, 4 = Dispute, 5 = Unknown, 6 = Voided trip
- fare_amount: time-and-distance fare in USD; extra, mta_tax, tolls_amount, improvement_surcharge,
  congestion_surcharge, Airport_fee: other charges in USD
- tip_amount: tip in USD (only card tips are recorded; cash tips are not)
- total_amount: total charged to passengers in USD (cash tips not included)

zones columns:
- LocationID: zone id, matches taxi.PULocationID and taxi.DOLocationID
- Borough: borough name
- Zone: zone name, e.g. 'JFK Airport', 'Midtown Center'
- service_zone: TLC service area
"""

# Added only in the `fixed` config: the one line that resolves Q12's ambiguity.
DEFINITION_FIX = """\
Vocabulary: "trip length" or "how long a trip is" means its duration, tpep_dropoff_datetime minus \
tpep_pickup_datetime, in minutes. "Trip distance" means trip_distance in miles.
"""

PROMPT = """\
You are a data assistant. Your role is to answer users' questions about their data by writing SQL.

You have access to a DuckDB SQL database with the following tables:

<tables>
{schema}
</tables>

<data_description>
{data_description}
</data_description>

For security reasons, you may only query these specific tables.

## SQL Query Guidelines

**No trailing semicolons.** Never end your query with a semicolon.
**Single statement only.** Return exactly one `SELECT` statement (CTEs are fine).
**No procedural or meta statements:** no EXPLAIN, SET, DDL (CREATE, ALTER, DROP), INTO, or transaction controls.
**Alias all computed/derived columns.**
**Percentile functions:** in DuckDB prefer `quantile_cont(col, 0.5)`.

## Answering Questions About Data

- Always use SQL for calculations (counting, averaging, etc.) - NEVER do manual calculations
- The query must return exactly one row and one column: the number that answers the question
- You do not see the data: the application runs your query and reports its result to the user
- Reply only with the JSON object the response schema describes

## Important Guidelines

- **Only answer data questions using SQL** - never use prior knowledge or assumptions about the data, even if the dataset seems familiar
- If a question is ambiguous, choose the most likely reading, say which one in `interpretation`, and lower `confidence`
"""


def _schema_lines(con, table: str) -> str:
    """Same text querychat's format_schema produces: type, Range for numbers and dates, values for small text sets."""
    cols = con.execute(f"DESCRIBE {table}").fetchall()
    lines = [f"Table: {table}", "Columns:"]
    for name, typ, *_ in cols:
        t = typ.upper()
        if "INT" in t:
            kind, sql_type = "numeric", "INTEGER"
        elif any(s in t for s in ("DOUBLE", "FLOAT", "DECIMAL")):
            kind, sql_type = "numeric", "FLOAT"
        elif "TIMESTAMP" in t:
            kind, sql_type = "date", "TIMESTAMP"
        elif "VARCHAR" in t:
            kind, sql_type = "text", "TEXT"
        else:
            kind, sql_type = "other", t
        lines.append(f"- {name} ({sql_type})")
        if kind in ("numeric", "date"):
            lo, hi = con.execute(f'SELECT MIN("{name}"), MAX("{name}") FROM {table}').fetchone()
            lines.append(f"  Range: {lo} to {hi}")
        elif kind == "text":
            n = con.execute(f'SELECT COUNT(DISTINCT "{name}") FROM {table}').fetchone()[0]
            if n <= CATEGORICAL_THRESHOLD:
                vals = [r[0] for r in con.execute(
                    f'SELECT DISTINCT "{name}" FROM {table} WHERE "{name}" IS NOT NULL ORDER BY 1').fetchall()]
                lines.append("  Categorical values: " + ", ".join(f"'{v}'" for v in vals))
    return "\n".join(lines)


_CACHE: dict[str, str] = {}
_PLOCK = threading.Lock()


def system_prompt(config: str = "baseline") -> str:
    if config not in ("baseline", "fixed"):
        raise ValueError(f"config {config!r}: baseline | fixed")
    with _PLOCK:  # inspect runs samples in threads; build the prompt once
        if config not in _CACHE:
            con = connect()
            schema = "\n\n".join(_schema_lines(con, t) for t in ("taxi", "zones"))
            desc = DATA_DESCRIPTION + ("\n" + DEFINITION_FIX if config == "fixed" else "")
            _CACHE[config] = PROMPT.format(schema=schema, data_description=desc.strip())
    return _CACHE[config]


if __name__ == "__main__":
    print(system_prompt())
