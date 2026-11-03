"""querychat over the NYC yellow-taxi table (January 2024), with a model selector.

Ask the sidebar things like "trips over 20 miles paid in cash" or
"average tip by passenger count". querychat turns the question into SQL,
DuckDB runs it on a local copy of the table, and the table and the three boxes update.

At start the app reads the Parquet file from S3 once, with its own (task role) credentials,
into a DuckDB database file on local disk, then switches off DuckDB's external access and locks
the configuration: the model's SQL can query the table but cannot read S3 or any file.

Environment (all read at start, never logged):
  GROQ_API_KEY, OPENAI_API_KEY  the model keys (on Fargate: the task definition's
                                 secrets list, from Secrets Manager)
  DASH_PASSWORD                  the password the page asks for; no password, no app
  QUESTION_CAP                   questions per browser session (default 15)
  TOTAL_CALLS                    model API calls per container, all sessions, every querychat feature
                                 (default 2000; a question is about 3 calls)
  GROQ_MODEL, OPENAI_NANO_MODEL, OPENAI_MINI_MODEL   model ids (defaults below)
  TAXI_S3 (or TAXI_BUCKET and TAXI_KEY), TAXI_REGION   the Parquet file and its bucket's region
  TAXI_DB                       the local DuckDB file (default /tmp/taxi.duckdb, Fargate's ephemeral disk)
  DUCKDB_MEMORY                 DuckDB's memory limit (default 400MB; it spills to disk beyond that)
  TRACES_TABLE, TRACE_TTL_DAYS, TRACES_REGION   optional per-question traces in DynamoDB (traces.py). Unset
                                 TRACES_TABLE: no traces, and the password page says nothing about them

Run locally: DASH_PASSWORD=... uv run shiny run app.py --port 8000
"""

import asyncio
import hmac
import os
import threading
import time
from pathlib import Path

import duckdb
import ibis
import querychat
from chatlas import ChatGroq, ChatOpenAI
from chatlas._provider_openai import OpenAIProvider
from chatlas._provider_openai_completions import OpenAICompletionsProvider
from shiny import App, reactive, render, ui

import traces

# s3://<bucket>/<key> of the trips Parquet file (data/README.md in the repo); deploy.sh sets it from BUCKET and KEY
TAXI_S3 = os.environ.get("TAXI_S3") or f"s3://{os.environ['TAXI_BUCKET']}/{os.environ.get('TAXI_KEY', 'genai/taxi_2024-01.parquet')}"
TAXI_REGION = os.environ.get("TAXI_REGION", "ca-central-1")
TAXI_DB = Path(os.environ.get("TAXI_DB", "/tmp/taxi.duckdb"))
DUCKDB_MEMORY = os.environ.get("DUCKDB_MEMORY", "400MB")

PASSWORD = os.environ.get("DASH_PASSWORD", "")
QUESTION_CAP = int(os.environ.get("QUESTION_CAP", "15"))
TOTAL_CALLS = int(os.environ.get("TOTAL_CALLS", "2000"))
MAX_LOGIN_TRIES = 5

MODELS = {
    "groq-qwen": ("Qwen 3.8 27B on Groq", "groq", os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")),
    "openai-nano": ("GPT-5.4 nano on OpenAI", "openai", os.environ.get("OPENAI_NANO_MODEL", "gpt-5.4-nano")),
    "openai-mini": ("GPT-5.4 mini on OpenAI", "openai", os.environ.get("OPENAI_MINI_MODEL", "gpt-5.4-mini")),
}
KEY_ENV = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}
AVAILABLE = {k: v for k, v in MODELS.items() if os.environ.get(KEY_ENV[v[1]])}

DATA_DESCRIPTION = """\
NYC yellow-taxi trips that started in January 2024, one row per trip (about 2.96 million rows),
from the NYC Taxi and Limousine Commission trip records.

- VendorID: 1 = Creative Mobile Technologies, 2 = VeriFone (Curb), 6 = Myle (a few hundred rows).
- tpep_pickup_datetime, tpep_dropoff_datetime: meter on and off, local New York time. A handful of
  rows have dates outside January 2024 (meter errors); for "January" filter on the pickup time.
- passenger_count: entered by the driver; 0 and NULL occur.
- trip_distance: miles on the meter.
- RatecodeID: 1 standard, 2 JFK, 3 Newark, 4 Nassau or Westchester, 5 negotiated, 6 group ride,
  99 unknown; NULL for about 140 thousand rows.
- store_and_fwd_flag: 'Y' or 'N' (uppercase).
- PULocationID, DOLocationID: TLC taxi-zone ids (1 to 265), no zone names in this table.
- payment_type: 0 flex fare (no payment recorded), 1 credit card, 2 cash, 3 no charge, 4 dispute.
  Tips are recorded for credit-card trips only, so tip questions should filter payment_type = 1.
- fare_amount, extra, mta_tax, tip_amount, tolls_amount, improvement_surcharge,
  congestion_surcharge, Airport_fee, total_amount: US dollars; negative values are refunds.
"""

GREETING = """\
Ask about NYC yellow-taxi trips from January 2024. For example:

* <span class="suggestion">Show trips longer than 20 miles paid in cash</span>
* <span class="suggestion">Which pickup zone has the highest average tip on card trips?</span>
* <span class="suggestion">Average fare by passenger count</span>

Every question goes to the model you picked above.
"""

def open_taxi_db() -> duckdb.DuckDBPyConnection:
    """Read the table from S3 once, then lock DuckDB so later SQL cannot reach S3 or files."""
    t0 = time.monotonic()
    for f in (TAXI_DB, TAXI_DB.with_name(TAXI_DB.name + ".wal")):
        f.unlink(missing_ok=True)  # always start from S3, never from a stale local copy
    db = duckdb.connect(str(TAXI_DB))
    db.execute(f"SET memory_limit = '{DUCKDB_MEMORY}'")
    db.execute(f"SET temp_directory = '{TAXI_DB}.tmp'")
    db.execute("SET autoinstall_known_extensions = false")
    db.execute("LOAD httpfs")
    db.execute("LOAD aws")  # installed in the image at build time
    # credential_chain finds the task role through the ECS container endpoint (locally: env or profile)
    db.execute(f"CREATE SECRET taxi_s3 (TYPE s3, PROVIDER credential_chain, REGION '{TAXI_REGION}')")
    db.execute(f"CREATE TABLE taxi AS SELECT * FROM read_parquet('{TAXI_S3}')")
    db.execute("DROP SECRET taxi_s3")
    db.execute("CHECKPOINT")
    n = db.execute("SELECT count(*) FROM taxi").fetchone()[0]
    print(f"loaded {n:,} rows from {TAXI_S3} in {time.monotonic() - t0:.1f} s", flush=True)
    return db


_db = open_taxi_db()
con = ibis.duckdb.from_connection(_db)  # ibis sets its own options (timezone) here, before the lock
_db.execute("SET enable_external_access = false")
_db.execute("SET lock_configuration = true")
taxi = con.table("taxi")

qc = querychat.QueryChat(
    taxi,
    "taxi",
    greeting=GREETING,
    data_description=DATA_DESCRIPTION,
    client=None,
    history=False,  # each browser session starts empty; no stored conversations
)

_calls_lock = threading.Lock()
_calls = {"n": 0}


class BudgetSpent(RuntimeError):
    pass


def _take_call() -> None:
    with _calls_lock:
        if _calls["n"] >= TOTAL_CALLS:
            raise BudgetSpent(f"The demo has used its {TOTAL_CALLS} model calls.")
        _calls["n"] += 1


def _guard_provider(cls) -> None:
    """Count every request any chat (forks included) sends through this provider class."""
    sync_fn, async_fn = cls.chat_perform, cls.chat_perform_async

    def chat_perform(self, *args, **kwargs):
        _take_call()
        return sync_fn(self, *args, **kwargs)

    async def chat_perform_async(self, *args, **kwargs):
        _take_call()
        return await async_fn(self, *args, **kwargs)

    cls.chat_perform, cls.chat_perform_async = chat_perform, chat_perform_async


# Groq goes through OpenAICompletionsProvider, OpenAI through OpenAIProvider (chatlas 0.23)
_guard_provider(OpenAIProvider)
_guard_provider(OpenAICompletionsProvider)


def make_client(model_key: str):
    _label, provider, model_id = MODELS[model_key]
    if provider == "groq":
        return ChatGroq(model=model_id)
    return ChatOpenAI(model=model_id)


class SessionCap:
    """Per-session question counter and trace context, shared by a client and its deep copies."""

    def __init__(self, asked, session_id: str, model_key: str):
        self.asked = asked
        self.session_id = session_id
        self.model_key = model_key

    def __deepcopy__(self, memo):
        return self


_capped_classes: dict[type, type] = {}


def capped_class(base: type) -> type:
    if base not in _capped_classes:

        class Capped(base):
            async def stream_async(self, *args, **kwargs):
                cap = self._session_cap
                asked = cap.asked
                n = asked.get()
                question = _question_text(args[0] if args else kwargs.get("message", ""))
                if n >= QUESTION_CAP:
                    _trace(cap, question, [], f"session cap of {QUESTION_CAP} questions reached", 0.0, 0)
                    return _canned(f"This session has used its {QUESTION_CAP} questions.")
                if _calls["n"] >= TOTAL_CALLS:
                    _trace(cap, question, [], "model-call budget spent", 0.0, QUESTION_CAP - n)
                    return _canned("The demo has used its model-call budget.")
                asked.set(n + 1)
                t0 = time.monotonic()
                n_turns = len(self.get_turns())
                try:
                    inner = await super().stream_async(*args, **kwargs)
                except Exception as e:
                    _trace(cap, question, self.get_turns()[n_turns:], f"{type(e).__name__}: {e}", time.monotonic() - t0,
                           QUESTION_CAP - n - 1)
                    raise
                return _traced(self, inner, cap, question, n_turns, t0, QUESTION_CAP - n - 1)

        _capped_classes[base] = Capped
    return _capped_classes[base]


async def _canned(text: str):
    yield text


def _question_text(x) -> str:
    if isinstance(x, str):
        return x
    return getattr(x, "text", None) or str(x)


def _trace(cap, question, turns, error, latency_s, questions_left):
    try:
        item = traces.make_item(
            session_id=cap.session_id, model_key=cap.model_key, model_id=MODELS[cap.model_key][2], question=question,
            summary=traces.summarize_turns(turns), error=error, latency_s=latency_s, questions_left=questions_left,
        )
        traces.record(item)
    except Exception as e:  # noqa: BLE001 - a trace must never break the answer
        print(f'{{"event": "trace_failed", "error": "{type(e).__name__}"}}', flush=True)


def _traced(chat, inner, cap, question, n_turns, t0, questions_left):
    def done(error):
        _trace(cap, question, chat.get_turns()[n_turns:], error, time.monotonic() - t0, questions_left)

    return traces.traced(inner, done)


# ui -----

gate_ui = ui.page_fixed(
    ui.h2("Taxi questions"),
    ui.p("This page is for the CPSC 436C lecture. Enter the password from the slide."),
    *([ui.p(f"Your questions are stored with their answers for {traces.TTL_DAYS} days to show how the app is "
            "monitored.")] if traces.ENABLED else []),
    ui.input_password("pw", "Password"),
    ui.input_action_button("login", "Enter"),
    ui.output_text("login_msg_out"),
    title="Taxi questions",
)

app_ui = ui.page_fillable(ui.output_ui("page"), title="Taxi questions", padding=0)


# server -----


def server(input, output, session):
    authed = reactive.value(False)
    tries = reactive.value(0)
    login_msg = reactive.value("")
    asked = reactive.value(0)  # per session, across model switches
    current = reactive.value(None)  # querychat ServerValues for the live chat
    n_chats = {"n": 0}

    @render.ui
    def page():
        if not authed():
            return gate_ui
        if not AVAILABLE:
            return ui.p("No model key is set in this container.")
        return ui.page_sidebar(
            ui.sidebar(
                ui.input_select(
                    "model",
                    "Model",
                    {k: v[0] for k, v in AVAILABLE.items()},
                ),
                ui.output_text("quota"),
                ui.div(
                    ui.input_action_button("reset_filters", "Reset filters", class_="btn-sm btn-outline-secondary"),
                    ui.input_action_button("reset_chat", "Reset chat", class_="btn-sm btn-outline-secondary"),
                    class_="d-flex gap-2",
                ),
                ui.output_ui("chat_panel"),
                width=420,
            ),
            ui.layout_columns(
                ui.value_box("Matching trips", ui.output_text("n_trips")),
                ui.value_box("Average fare", ui.output_text("avg_fare")),
                ui.value_box("Average distance", ui.output_text("avg_dist")),
                col_widths=[4, 4, 4],
                fill=False,
            ),
            ui.card(
                ui.card_header(ui.output_text("title")),
                ui.output_data_frame("table"),
                fill=True,
            ),
            title="NYC yellow taxi, January 2024",
            fillable=True,
        )

    @render.text
    def login_msg_out():
        return login_msg()

    @reactive.effect
    @reactive.event(input.login)
    async def _login():
        if tries() >= MAX_LOGIN_TRIES:
            login_msg.set("Too many tries. Reload the page to try again.")
            return
        tries.set(tries() + 1)
        await asyncio.sleep(1)  # slows guessing
        given = input.pw() or ""
        if PASSWORD and hmac.compare_digest(given.encode(), PASSWORD.encode()):
            authed.set(True)
        else:
            login_msg.set("Wrong password." if PASSWORD else "This page has no password set.")

    def start_chat(model_key: str):
        n_chats["n"] += 1
        mod_id = f"qc{n_chats['n']}"
        vals = qc.server(id=mod_id, client=make_client(model_key))
        # The cap lives on the client's class, not on the instance: querychat deep-copies the
        # client for its side features, and a copy keeps its class (and so the cap) but runs on itself.
        vals.client._session_cap = SessionCap(asked, session.id, model_key)
        vals.client.__class__ = capped_class(type(vals.client))
        current.set((mod_id, vals))

    @reactive.effect
    def _model_changed():
        if not authed() or not AVAILABLE:
            return
        key = input.model()
        if key not in AVAILABLE:
            return
        with reactive.isolate():
            start_chat(key)

    def _event_trace(event: str):
        try:
            traces.record(traces.make_event_item(
                session_id=session.id, event=event, questions_left=max(QUESTION_CAP - asked.get(), 0)))
        except Exception as e:  # noqa: BLE001 - a trace must never break the app
            print(f'{{"event": "trace_failed", "error": "{type(e).__name__}"}}', flush=True)

    @reactive.effect
    @reactive.event(input.reset_filters)
    def _reset_filters():
        # querychat's own reset: its update/reset_dashboard tools set the session's sql and title to None
        cur = current.get()
        if cur is None:
            return
        cur[1].sql.set(None)
        cur[1].title.set(None)
        _event_trace("reset_filters")

    @reactive.effect
    @reactive.event(input.reset_chat)
    async def _reset_chat():
        # clears the messages and the model's turns; the question counter (asked) is per session and stays
        cur = current.get()
        if cur is None:
            return
        vals = cur[1]
        if vals.chat is not None:
            await vals.chat.clear_messages()
        vals.client.set_turns([])
        vals.sql.set(None)
        vals.title.set(None)
        _event_trace("reset_chat")

    @render.ui
    def chat_panel():
        cur = current()
        if cur is None:
            return ui.p("Starting...")
        mod_id, _vals = cur
        return qc.ui(id=mod_id)

    @render.text
    def quota():
        return f"Questions left in this session: {max(QUESTION_CAP - asked(), 0)} of {QUESTION_CAP}"

    def df():
        cur = current()
        if cur is None:
            return taxi
        return cur[1].df()

    @render.text
    def title():
        cur = current()
        return (cur and cur[1].title()) or "All trips"

    @render.text
    def n_trips():
        return f"{df().count().execute():,}"

    @render.text
    def avg_fare():
        t = df()
        if "fare_amount" not in t.columns:
            return "-"
        v = t.fare_amount.mean().execute()
        return "-" if v is None else f"${v:.2f}"

    @render.text
    def avg_dist():
        t = df()
        if "trip_distance" not in t.columns:
            return "-"
        v = t.trip_distance.mean().execute()
        return "-" if v is None else f"{v:.1f} mi"

    @render.data_frame
    def table():
        return df().limit(500).execute()


app = App(app_ui, server)
