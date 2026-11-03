# Failing question: q12

**Question:** What is the average trip length?

**Reference reading:** trip length = duration from pickup to dropoff, in minutes. **Reference value:** 15.6130 (tolerance 1%).
**Reference SQL:**

```sql
SELECT AVG(epoch(tpep_dropoff_datetime - tpep_pickup_datetime)) / 60 AS avg_minutes FROM taxi
```

**The other reading:** trip length = trip_distance, in miles, value 3.6522.

Passed 1 of 9 samples across models and epochs.

## Prompt

System prompt (the same for every question; querychat's structure, schema and data description):

<details><summary>show the system prompt</summary>

```
You are a data assistant. Your role is to answer users' questions about their data by writing SQL.

You have access to a DuckDB SQL database with the following tables:

<tables>
Table: taxi
Columns:
- VendorID (INTEGER)
  Range: 1 to 6
- tpep_pickup_datetime (TIMESTAMP)
  Range: 2002-12-31 22:59:39 to 2024-02-01 00:01:15
- tpep_dropoff_datetime (TIMESTAMP)
  Range: 2002-12-31 23:05:41 to 2024-02-02 13:56:52
- passenger_count (INTEGER)
  Range: 0 to 9
- trip_distance (FLOAT)
  Range: 0.0 to 312722.3
- RatecodeID (INTEGER)
  Range: 1 to 99
- store_and_fwd_flag (TEXT)
  Categorical values: 'N', 'Y'
- PULocationID (INTEGER)
  Range: 1 to 265
- DOLocationID (INTEGER)
  Range: 1 to 265
- payment_type (INTEGER)
  Range: 0 to 4
- fare_amount (FLOAT)
  Range: -899.0 to 5000.0
- extra (FLOAT)
  Range: -7.5 to 14.25
- mta_tax (FLOAT)
  Range: -0.5 to 4.0
- tip_amount (FLOAT)
  Range: -80.0 to 428.0
- tolls_amount (FLOAT)
  Range: -80.0 to 115.92
- improvement_surcharge (FLOAT)
  Range: -1.0 to 1.0
- total_amount (FLOAT)
  Range: -900.0 to 5000.0
- congestion_surcharge (FLOAT)
  Range: -2.5 to 2.5
- Airport_fee (FLOAT)
  Range: -1.75 to 1.75

Table: zones
Columns:
- LocationID (INTEGER)
  Range: 1 to 265
- Borough (TEXT)
  Categorical values: 'Bronx', 'Brooklyn', 'EWR', 'Manhattan', 'N/A', 'Queens', 'Staten Island', 'Unknown'
- Zone (TEXT)
- service_zone (TEXT)
  Categorical values: 'Airports', 'Boro Zone', 'EWR', 'N/A', 'Yellow Zone'
</tables>

<data_description>
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
```

</details>

User message:

```
What is the average trip length?
```

Response format: JSON schema `answer` (strict): `sql`, `unit`, `interpretation`, `confidence`.

## Why it fails

The question does not say whether length is time or distance. 7 of 9 samples answered the other reading (trip length = trip_distance, in miles); their SQL is fine and runs, so only the value gate catches it, and the `unit` field shows which reading the model took. The prompt asks the model to lower `confidence` when a question is ambiguous; confidence stated on this question: high 7, low 1, medium 1.

## What each model returned (epoch 1)

### GPT-5.4 mini (OpenAI) (`gpt-5.4-mini`)

Model output:

```json
{"sql":"SELECT avg(trip_distance) AS average_trip_length FROM taxi","unit":"miles","interpretation":"Interpreting \"trip length\" as the average taxi trip distance in miles across all records in the taxi table.","confidence":"high"}
```

Scorer verdicts:

| scorer | verdict | explanation |
|---|---|---|
| schema_valid | pass | valid |
| sql_runs | pass | 1 rows x 1 cols |
| value_correct | fail | 3.6522 vs reference 15.6130 (tol 1%); it matches the other reading (trip length = trip_distance, in miles: 3.6522) |

DuckDB returned **3.6522**; outcome **value mismatch**; 1350 tokens in, 57 out, 0.665 s.

Other epochs: epoch 2: value mismatch (miles, value 3.65); epoch 3: value mismatch (miles, value 3.65)

### GPT-5.4 nano (OpenAI) (`gpt-5.4-nano`)

Model output:

```json
{"sql":"SELECT AVG(trip_distance) AS avg_trip_length_miles FROM taxi","unit":"miles","interpretation":"Average of trip_distance (reported trip length in miles) across all trips in the taxi table.","confidence":"high"}
```

Scorer verdicts:

| scorer | verdict | explanation |
|---|---|---|
| schema_valid | pass | valid |
| sql_runs | pass | 1 rows x 1 cols |
| value_correct | fail | 3.6522 vs reference 15.6130 (tol 1%); it matches the other reading (trip length = trip_distance, in miles: 3.6522) |

DuckDB returned **3.6522**; outcome **value mismatch**; 1350 tokens in, 55 out, 0.853 s.

Other epochs: epoch 2: value mismatch (miles, value 3.65); epoch 3: value mismatch (miles, value 3.65)

### Qwen 3.8 27B (Groq) (`qwen/qwen3.8-27b`)

Model output:

```json
{"confidence": "high", "interpretation": "Average (mean) trip_distance in miles across all trips in the taxi table.", "sql": "SELECT AVG(trip_distance) AS avg_trip_length_miles FROM taxi; ", "unit": "miles"}
```

Scorer verdicts:

| scorer | verdict | explanation |
|---|---|---|
| schema_valid | pass | valid |
| sql_runs | pass | 1 rows x 1 cols |
| value_correct | fail | 3.6522 vs reference 15.6130 (tol 1%); it matches the other reading (trip length = trip_distance, in miles: 3.6522) |

DuckDB returned **3.6522**; outcome **value mismatch**; 1310 tokens in, 57 out, 1.395 s.

Other epochs: epoch 2: pass (minutes, value 15.61); epoch 3: SQL error (minutes, value none)

## After one line in the data description

The `fixed` config adds one vocabulary line to `<data_description>`:

```
Vocabulary: "trip length" or "how long a trip is" means its duration, tpep_dropoff_datetime minus tpep_pickup_datetime, in minutes. "Trip distance" means trip_distance in miles.
```

| model | passed | units returned |
|---|---|---|
| GPT-5.4 mini (OpenAI) | 3/3 | minutes |
| GPT-5.4 nano (OpenAI) | 3/3 | minutes |
| Qwen 3.8 27B (Groq) | 1/3 | minutes |
