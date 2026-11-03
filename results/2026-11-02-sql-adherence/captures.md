# SQL adherence: captures for the deck

Run 2026-11-02. Models `qwen/qwen3.8-27b` (Groq), `gpt-5.4-nano`, `gpt-5.4-mini` (OpenAI). 12 questions x 3 epochs per model and variant. Raw files in this folder: `summary.jsonl`, `samples.jsonl`, `repairs.jsonl` (every post-processing change), `diagnosis.jsonl` (the correctness runs' SQL errors), `json_cut_offline.jsonl` (the cut applied to the json run's replies).

Line for the slide: fix in code what code can fix safely, and spend a model call only on what is left.

## 1. Headline: cut + validator against validator alone (Qwen 3.8 27B, 36 answers each)

| variant | SQL errors | value correct | cuts | retries (model calls) | price | median latency |
|---|---:|---:|---:|---:|---:|---:|
| json+pydantic | 0% | 83% | 0 | 13 | $0.1091 | 0.63 s |
| json+cut+pydantic | 3% | 89% | 9 | 5 | $0.0653 | 0.46 s |
| pydantic | 0% | 89% | 0 | 4 | $0.0613 | 0.4 s |
| cut+pydantic | 0% | 92% | 0 | 5 | $0.0629 | 0.54 s |

With strict JSON mode on, the cut does the work in code and the validator's retries fall from 13 to 5, the price by 40%. Without JSON mode Qwen writes no junk after the query, so the cut finds nothing (0 cuts) and the two rows are within a retry of each other. GPT-5.4 nano and mini: 0% SQL errors with the validator, in every variant.

## 2. One Qwen reply the cut fixes (json+cut+pydantic, q04, epoch 1)

**Question:** What is the average tip amount, in dollars, on trips paid by credit card?

Before the cut (the scorer refuses it: more than one statement):

```sql
SELECT AVG(tip_amount) AS average_tip_amount FROM taxi WHERE payment_type = 1 AND tip_amount IS NOT NULL; -- no ending semicolon
```

After the cut (nothing rewritten, DuckDB returns 4.17, the reference 4.17):

```sql
SELECT AVG(tip_amount) AS average_tip_amount FROM taxi WHERE payment_type = 1 AND tip_amount IS NOT NULL
```

## 3. One reply the validator catches and the retry fixes (json+cut+pydantic, q02, epoch 3)

**Question:** What is the average trip distance in miles?

First reply's SQL:

```sql
SELECT
  ROUND(average(trip_distance), 2) AS avg_trip_distance_miles
FROM taxi
```

Validator's message, sent back to the model:

```
sql: DuckDB cannot plan the query: Catalog Error: Scalar Function with name average does not exist!
```

Retried SQL (passes, DuckDB returns 3.650):

```sql
SELECT
  ROUND(avg(trip_distance), 2) AS avg_trip_distance_miles
FROM taxi
```

## 4. One Qwen failure without either fix (json, q03, epoch 1)

**Question:** How many trips were paid in cash?

```sql
SELECT COUNT(*) AS cash_trips FROM taxi WHERE payment_type = 2;"}
```

DuckDB: `Parser Error: unterminated quoted identifier`. The scorer refuses it first: refused: more than one statement.

## 5. The full grid, Qwen 3.8 27B (SQL errors / value correct / price)

| variant | SQL errors | value correct | price |
|---|---:|---:|---:|
| baseline | 6% | 83% | $0.0545 |
| instructions | 0% | 81% | $0.0598 |
| json | 28% | 56% | $0.0513 |
| pydantic | 0% | 89% | $0.0613 |
| cut | 11% | 78% | $0.0548 |
| rewrite | 3% | 89% | $0.0548 |
| cut+pydantic | 0% | 92% | $0.0629 |
| json+pydantic | 0% | 83% | $0.1091 |
| json+cut+pydantic | 3% | 89% | $0.0653 |
| repair | 3% | 81% | $0.0540 |
| all | 0% | 83% | $0.0687 |
| all-instructions | 3% | 86% | $0.0652 |
| all-json | 0% | 92% | $0.0621 |
| all-pydantic | 19% | 61% | $0.0622 |
| all-repair | 0% | 89% | $0.0742 |

*repair*, *all* and *all-…* ran the first post-processing (a plain split at `;`, comments dropped, then rewrite). *all* = instructions + json + pydantic + repair.

## 6. One rewrite diff (rewrite, Qwen, q10, epoch 1: transpile)

```sql
SELECT COUNT(*) AS trip_count FROM taxi t JOIN zones pu ON t.PULocationID = pu.LocationID JOIN zones do ON t.DOLocationID = do.LocationID WHERE pu.Borough = 'Manhattan' AND do.Borough = 'Brooklyn'
```

becomes (DuckDB returns 52,145, the reference)

```sql
SELECT COUNT(*) AS trip_count FROM taxi AS t JOIN zones AS pu ON t.PULocationID = pu.LocationID JOIN zones AS "do" ON t.DOLocationID = "do".LocationID WHERE pu.Borough = 'Manhattan' AND "do".Borough = 'Brooklyn'
```

## 7. The risk: a plain split that turned an error into a wrong number (all, Qwen, q08, epoch 2)

```sql
SELECT ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS cash_trip_pct FROM taxi WHERE payment_type = 2; 0
```

became

```sql
SELECT ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS cash_trip_pct FROM taxi WHERE payment_type = 2
```

It runs and returns 100 against the reference 14.81: the query before the stray ` 0` divides cash trips by cash trips. The sqlglot cut changed no answer's value in these runs.

## Fixes and Huyen, AI Engineering ch. 2

| fix | level | here |
|---|---|---|
| instructions | prompting | DuckDB named, the query alone in `sql`, 3 example queries |
| json | constrained sampling | the provider's strict JSON-schema mode |
| pydantic | test-time retries | a validator on `sql` (sqlglot parse, one SELECT, known columns, EXPLAIN) and one retry with its message |
| cut, rewrite | post-processing | cut: first complete statement, never rewritten; rewrite: sqlglot transpile and near-miss columns |

Not tried: GEPA prompt optimization in DSPy, set aside on purpose: it needs its own held-out training questions (a later lecture or a project option).
