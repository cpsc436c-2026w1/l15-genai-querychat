# dashboard

The taxi questions app as a web page: querychat over the NYC yellow-taxi table of January 2024 (2,964,624 trips),
with a model selector (Qwen 3.8 27B on Groq, GPT-5.4 nano and GPT-5.4 mini on OpenAI), a password page, a cap of
15 questions per browser session and 2,000 model calls per container (about 3 calls per question). It runs as one
container on AWS Fargate. Adapted from the DSCI 532 groqdemo app and the taxi apps of DSCI 532 lecture 7.

## Data: read from S3 once, then locked

The table is not in the image. At start, before querychat gets the connection, `app.py`:

1. opens a DuckDB database file on the container's local disk (`/tmp/taxi.duckdb`, with a 400 MB memory limit
   and spilling to that disk beyond it).
2. loads the `httpfs` and `aws` extensions, installed in the image at build, so nothing is downloaded at start.
3. creates an S3 secret with `PROVIDER credential_chain`, which finds the task role's credentials.
4. copies `s3://$BUCKET/$KEY` into table `taxi`, then drops the secret.
5. sets `enable_external_access = false`, then `lock_configuration = true`.

After that the model's SQL can query `taxi` but cannot read S3 or any file, and it cannot switch the setting
back. The task role is the only credential the app holds, and it may read one object. The model keys reach the
app as environment variables, injected by ECS from Secrets Manager at task start. The app makes no AWS call
after the S3 read.

## Traces: one DynamoDB item per question (optional)

With `TRACES_TABLE` set, after every question, answered or failed, `traces.py` writes one item to that table
(pk `session_id`, the Shiny session id; sk `ts`, ISO time plus a counter): `model`, `question` (the full text),
`sql` (the last SQL the model sent to querychat's tools, or null), `ok`, `error` (the failed tool result or
exception, or null), `tokens_in` (all input, cached included), `tokens_cached`, `tokens_out`, `cost_usd` (list
prices, `traces.PRICES`), `latency_s`, `questions_left` and `expires_at` (now + `TRACE_TTL_DAYS` days, after which
DynamoDB's TTL deletes the item). No key, no password, no IP address. The password page then says: "Your questions
are stored with their answers for 7 days to show how the app is monitored", with your number of days. With
`TRACES_TABLE` unset, nothing is written and the page does not mention traces.

The write runs in a background thread with the task role. A failed write prints
`{"event": "trace_write_failed", ...}` and the answer goes on. Each question also prints one JSON line,
`{"event": "question", ...}`. It leaves out the question text and the SQL, and CloudWatch Logs still shows activity. Tokens are the
main chat's calls for that question (the tool loop). querychat's side features run on copies and are not counted.
Unit tests with the DynamoDB call faked: `uv run --with pytest pytest -q tests`.

Two buttons under the question counter, each traced as a small item (`session_id`, `ts`, `event`, `questions_left`,
`expires_at`). Question items carry `event: question`, so the table has one event field:

- **Reset filters** (`reset_filters`): sets querychat's session `sql` and `title` back to None, the same thing its
  reset_dashboard tool does, so the table and the three boxes show all the trips again.
- **Reset chat** (`reset_chat`): clears the messages (`chat.clear_messages()`) and the model's turns
  (`client.set_turns([])`, which keeps the system prompt), and resets the filter. The question counter stays as it
  is, so a reset does not give back questions.

Read one session: `bash traces.sh session <session_id>`. "Which model failed most this week" is a Scan of the whole
table: that question belongs in CloudWatch Logs Insights over the JSON lines, or in S3 + Athena.

To switch traces on: set `TRACES_TABLE` (in your shell or `dashboard/.env`), run `bash traces.sh create`, give the
task role its PutItem permission (setup list below), then `bash deploy.sh`.

## SQL checks: cut and validator

The sidebar has a switch, "SQL checks", on by default, per browser session. The reset buttons leave it as it is.
When it is on, `sqlchecks.py` runs inside querychat's two SQL tools (`querychat_update_dashboard` and
`querychat_query`) before DuckDB sees the model's SQL:

1. **cut**: sqlglot finds the end of the first complete DuckDB statement and drops the text after it (a stray `"}`,
   comments, a second query). Nothing is rewritten, and a `;` inside a string literal is not a boundary.
2. **validator**: one statement, a SELECT (or WITH or UNION), tables and columns that exist in `taxi`, then DuckDB's
   EXPLAIN. On a failure the tool returns `SQL check: <reason>` as its error. The model reads it on its next turn and
   can send fixed SQL. That is querychat's own tool loop, so the checks add no loop code, and `TOTAL_CALLS` and the
   15-question cap count those turns.

The SQL adherence eval (`evals/sql_adherence/`) measures the same two checks on the correctness questions and
imports them from `sqlchecks.py`, so there is one copy of the code. Tests: `tests/test_sqlchecks.py`.

**How it hooks in.** After `qc.server()` builds a session's client, `start_chat` wraps the `func` of those two chatlas
`Tool` objects in `vals.client._tools`. The model's `query` argument is cut and checked, then the original function
runs with the cut SQL, so querychat stores and later re-runs the clean SQL. The wrap is per session (each session has
its own client) and needs no querychat subclass or patch. With the switch off, the wrapper calls the original with
the same arguments. A data-source subclass (`IbisSource.execute_query` or `test_query`) would also see the
dashboard's own re-runs and is shared by all sessions, so a per-session switch would need a context lookup.

Trace items get `sql_checks` ("on" or "off"), `cut_applied`, `cut_removed` (the dropped text, 200 characters at most,
or null), `validator_rejections` (a count) and `validator_messages` (each 300 characters at most). The stdout line
gets `sql_checks`, `cut_applied` and `validator_rejections`, counts and flags only.

In querychat's tool loop the SQL travels as a tool argument, not inside a JSON reply, which is where the eval found
the debris after the query. So expect the cut to fire rarely here, and the validator to catch the queries that name
a column or a function that does not exist.

## Tool-call log in the trace item

Each question item also holds what happened inside querychat's tool loop, still as **one item per question**:

- `tool_calls`: one map per tool call, in order, with `name` (`querychat_get_schema`, `querychat_query`,
  `querychat_update_dashboard` and so on), `args` (the SQL cut at 2,000 characters, other strings at 500),
  `result_kind` (`ok` or `error`), `error` (the message, 500 characters at most) or `rows` (when the result is a list
  of rows, which `querychat_query` returns), `check` (`pass`, `reject` or `off`) and `cut_removed` for the two SQL
  tools, and `latency_s`, timed by a wrapper around every tool's function (`sqlchecks.wrap_timing`). At most 20
  entries, and `truncated` is true when there were more.
- `n_tool_calls`, and `reply`: the model's last text, 4,000 characters at most. The question is kept to 4,000
  characters and the top-level `sql` to 2,000.

Why one item per question and not one per tool call: one `traces.sh session <id>` Query still returns the session in
order, a question and its calls are read together without a join, there is one write per question (one write unit
per KB), and the item stays far under DynamoDB's 400 KB limit. The worst case the limits allow (20 calls with
2,000-character SQL, a 4,000-character question and reply) is under 60 KB (`tests/test_traces.py`). The stdout line
adds `n_tool_calls`, `truncated` and `item_bytes`, counts only. With `TRACES_TABLE` unset, nothing is written or
printed, as for the rest of the trace.

## Scripts

All of them source `common.sh`, which holds the settings and checks the account and the region before any call.

| script | what it does | AWS |
|---|---|---|
| `common.sh` | settings with defaults: `REGION`, `ACCOUNT` (from `aws sts get-caller-identity`), `NAME`, `BUCKET`, `KEY`, `SECRET_NAME`, `EXEC_ROLE_NAME`, `TASK_ROLE_NAME`, `IMAGE_TAG`, and for traces `TRACES_TABLE` (empty: no traces), `TRACE_TTL_DAYS` (7), `TRACES_REGION` (`REGION`) | read |
| `deploy.sh` | ECR repo (keeps the last 3 images), image build (arm64) and push, log group (7 days), cluster, security group (port 8000), task definition (0.5 vCPU, 1 GB, ARM64). Starts nothing. Needs `BUCKET` and `DASH_PASSWORD` | write |
| `start.sh [revision]` | one Fargate task with a public IP, then its URL. Bills until `stop.sh` | write |
| `url.sh` | the running task's URL | read |
| `stop.sh` | stops the task and keeps everything else | write |
| `traces.sh create\|describe\|session ID\|delete` | the optional trace table `$TRACES_TABLE`: create it (on demand, TTL on `expires_at`), show it, read one browser session (one Query), delete it | write (`create`, `delete`), read |
| `teardown.sh` | removes everything `deploy.sh` made, the trace table too when `TRACES_TABLE` is set, and lists what is left. Keeps the roles and the secret | write |

```bash
export BUCKET=<your bucket>            # holding $KEY, default genai/taxi_2024-01.parquet (bash data/fetch.sh, then upload)
read -rs DASH_PASSWORD; export DASH_PASSWORD
bash deploy.sh && bash start.sh        # about 2 minutes, prints http://<ip>:8000/
bash stop.sh                           # when you are done (bash teardown.sh removes the rest)
```

What it costs while it runs is on the Cost report page: about $0.027 an hour in ca-central-1, plus the model calls.

## Set up first, by whoever owns the account

| what | allowed to do |
|---|---|
| secret `$SECRET_NAME` | a JSON object with `GROQ_API_KEY` and `OPENAI_API_KEY` |
| execution role `$EXEC_ROLE_NAME`, trusted by `ecs-tasks.amazonaws.com` | pull the image from ECR, write to the log group, read that one secret (`secretsmanager:GetSecretValue`) |
| task role `$TASK_ROLE_NAME`, trusted by `ecs-tasks.amazonaws.com` | `s3:GetObject` on `$BUCKET/$KEY`, and with traces on `dynamodb:PutItem` on `$TRACES_TABLE` only. Nothing else |
| whoever runs the scripts | ECR, ECS, CloudWatch Logs and security groups in the default VPC, DynamoDB on `$TRACES_TABLE` (create, describe, query, delete, TTL) when traces are on, `iam:GetRole` and `iam:PassRole` on the two roles, `secretsmanager:DescribeSecret` on the secret |

The password is a plain environment variable of the task definition: anyone who can describe task definitions in
the account can read it. It is never written to the repo or the image.

## Run locally

```bash
uv sync
TAXI_S3=s3://$BUCKET/$KEY DASH_PASSWORD=test uv run shiny run app.py --port 8000    # your AWS credentials read the file
```

Without the two model keys the password page works and the dashboard says no model key is set. With
`GROQ_API_KEY` or `OPENAI_API_KEY` in the environment the chat works.
