"""inspect logs -> results/<date>-correctness/: summary.jsonl, per_question.jsonl, samples.jsonl, failing_trace.md.

    uv run python -m evals.correctness.report [--log-dir logs]

Outcome per sample is the first failing gate (API error, schema failure, SQL error, value mismatch) or pass.
Cost uses the provider list prices below, read on the date stated; cached input is billed at the cached rate."""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import pandas as pd
from inspect_ai.log import list_eval_logs, read_eval_log

from evals.correctness.build_questions import load
from harness.prompts import system_prompt

ROOT = Path(__file__).resolve().parents[2]
PRICES_DATE = "2026-11-02"
PRICES = {  # USD per 1M tokens: input, cached input, output
    "qwen/qwen3.8-27b": (0.80, None, 4.00),  # console.groq.com/docs/models
    "gpt-5.4-mini": (0.75, 0.075, 4.50),      # developers.openai.com/api/docs/pricing, standard tier
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
}
LABEL = {"qwen/qwen3.8-27b": "Qwen 3.8 27B (Groq)", "gpt-5.4-nano": "GPT-5.4 nano (OpenAI)",
         "gpt-5.4-mini": "GPT-5.4 mini (OpenAI)"}


def cost(model, tin, tcached, tout):
    p = PRICES.get(model)
    if not p:
        return float("nan")
    pin, pc, pout = p
    unc = tin - (tcached if pc else 0)
    return (unc * pin + (tcached * pc if pc else 0) + tout * pout) / 1e6


def rows(log_dir: Path) -> pd.DataFrame:
    out = []
    for info in list_eval_logs(str(log_dir)):
        log = read_eval_log(info.name)
        if log.status != "success":
            continue
        md = log.eval.metadata or {}
        for s in log.samples:
            st = s.store or {}
            sc = s.scores or {}
            vc = sc.get("value_correct")
            v = (vc.metadata or {}) if vc else {}
            outcome = v.get("outcome") or ("API error" if st.get("error") else "?")
            out.append(dict(
                log=Path(info.name).name, created=log.eval.created, model=md.get("model_id"), provider=md.get("provider"),
                config=md.get("config"), id=s.id, epoch=s.epoch, question=s.input,
                outcome=outcome, value=v.get("value"), reference=s.metadata.get("reference_value"),
                value_note=v.get("value_note"), schema_error=v.get("schema_error"), sql_error=v.get("sql_error"),
                sql=(v.get("answer") or {}).get("sql"), unit=(v.get("answer") or {}).get("unit"),
                interpretation=(v.get("answer") or {}).get("interpretation"),
                confidence=(v.get("answer") or {}).get("confidence"),
                text=st.get("text"), reasoning=st.get("reasoning"), api_error=st.get("error"),
                tokens_in=st.get("tokens_in") or 0, tokens_out=st.get("tokens_out") or 0,
                tokens_cached=st.get("tokens_cached") or 0, tokens_reasoning=st.get("tokens_reasoning") or 0,
                latency_s=st.get("latency_s"), retries=st.get("retries") or 0,
                scores={k: (x.value, x.explanation) for k, x in sc.items()},
            ))
    return pd.DataFrame(out)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    recs = []
    for (model, config), g in df.groupby(["model", "config"], sort=False):
        tin, tc, tout = g.tokens_in.sum(), g.tokens_cached.sum(), g.tokens_out.sum()
        recs.append({
            "model": LABEL.get(model, model), "model_id": model, "config": config,
            "questions": g.id.nunique(), "samples": len(g),
            "pass rate": f"{(g.outcome == 'pass').mean():.0%}",
            "schema failures": int((g.outcome == "schema failure").sum()),
            "SQL errors": int((g.outcome == "SQL error").sum()),
            "value mismatches": int((g.outcome == "value mismatch").sum()),
            "API errors": int((g.outcome == "API error").sum()),
            "tokens in": int(tin), "tokens out": int(tout), "total tokens": int(tin + tout),
            "cost USD": round(cost(model, tin, tc, tout), 4),
            "median latency s": round(statistics.median(g.latency_s.dropna()), 2) if g.latency_s.notna().any() else None,
        })
    return pd.DataFrame(recs)


def per_question(df: pd.DataFrame) -> pd.DataFrame:
    base = df[df.config == "baseline"]
    t = base.assign(ok=base.outcome == "pass").groupby(["id", "model"]).ok.agg(lambda s: f"{s.sum()}/{len(s)}")
    t = t.unstack("model").rename(columns=LABEL)
    q = base.drop_duplicates("id").set_index("id")[["question", "reference"]]
    return q.join(t)


def sql_kinds(df: pd.DataFrame) -> pd.DataFrame:
    e = df[df.outcome == "SQL error"].copy()
    e["kind"] = e.sql_error.str.extract(r"^(refused: [^;]+|\w+Exception)", expand=False).fillna("other")
    e["model"] = e.model.map(lambda m: LABEL.get(m, m))
    return e.groupby(["model", "config", "kind"]).size().reset_index(name="samples")


def fence(s, lang=""):
    return f"```{lang}\n{(s or '').strip()}\n```"


def failing_trace(df: pd.DataFrame, meta: dict, qid: str | None = None) -> str:
    base = df[df.config == "baseline"]
    rate = base.assign(ok=base.outcome == "pass").groupby("id").ok.mean().sort_values(kind="stable")
    qid = qid or rate.index[0]
    m = meta[qid]
    g = base[base.id == qid]
    L = [f"# Failing question: {qid}", "",
         f"**Question:** {m['question']}", "",
         f"**Reference reading:** {m.get('reading', 'as asked')}. **Reference value:** {m['reference_value']:,.4f} "
         f"(tolerance {m['rel_tol']:.0%}).",
         "**Reference SQL:**", "", fence(m["sql"], "sql"), ""]
    if m.get("alt_reading"):
        L += [f"**The other reading:** {m['alt_reading']}, value {m['alt_value']:,.4f}.", ""]
    L += [f"Passed {int((g.outcome == 'pass').sum())} of {len(g)} samples across models and epochs.", "",
          "## Prompt", "",
          "System prompt (the same for every question; querychat's structure, schema and data description):", "",
          "<details><summary>show the system prompt</summary>", "", fence(system_prompt("baseline")), "", "</details>",
          "", "User message:", "", fence(m["question"]), "",
          "Response format: JSON schema `answer` (strict): `sql`, `unit`, `interpretation`, `confidence`.", ""]
    if m.get("alt_reading"):
        alt = g.value_note.fillna("").str.contains("other reading")
        conf = g.confidence.value_counts().to_dict()
        L += ["## Why it fails", "",
              f"The question does not say whether length is time or distance. {int(alt.sum())} of {len(g)} samples "
              f"answered the other reading ({m['alt_reading']}); their SQL is fine and runs, so only the value gate "
              "catches it, and the `unit` field shows which reading the model took. The prompt asks the model to "
              "lower `confidence` when a question is ambiguous; confidence stated on this question: "
              + ", ".join(f"{k} {v}" for k, v in conf.items()) + ".", ""]
    L += ["## What each model returned (epoch 1)", ""]
    for model, gm in g.groupby("model", sort=False):
        r = gm.sort_values("epoch").iloc[0]
        L += [f"### {LABEL.get(model, model)} (`{model}`)", "", "Model output:", "", fence(r.text, "json"), ""]
        L += ["Scorer verdicts:", "", "| scorer | verdict | explanation |", "|---|---|---|"]
        for k in ("schema_valid", "sql_runs", "value_correct"):
            val, expl = r.scores.get(k, (None, ""))
            L.append(f"| {k} | {'pass' if val == 'C' else 'fail'} | {(expl or '').replace('|', '/')} |")
        L += ["", f"DuckDB returned **{r.value if r.value is None else f'{r.value:,.4f}'}**; outcome **{r.outcome}**; "
              f"{r.tokens_in} tokens in, {r.tokens_out} out, {r.latency_s} s.", ""]
        other = gm.sort_values("epoch").iloc[1:]
        if len(other):
            L += ["Other epochs: " + "; ".join(f"epoch {e.epoch}: {e.outcome} ({e.unit}, value "
                                               f"{'none' if pd.isna(e.value) else f'{e.value:,.2f}'})"
                                               for e in other.itertuples()), ""]
    fixed = df[(df.config == "fixed") & (df.id == qid)]
    if len(fixed):
        L += ["## After one line in the data description", "",
              "The `fixed` config adds one vocabulary line to `<data_description>`:", "",
              fence("Vocabulary: \"trip length\" or \"how long a trip is\" means its duration, tpep_dropoff_datetime "
                    "minus tpep_pickup_datetime, in minutes. \"Trip distance\" means trip_distance in miles."), "",
              "| model | passed | units returned |", "|---|---|---|"]
        for model, gm in fixed.groupby("model", sort=False):
            L.append(f"| {LABEL.get(model, model)} | {int((gm.outcome == 'pass').sum())}/{len(gm)} | "
                     f"{', '.join(sorted(set(map(str, gm.unit))))} |")
        L.append("")
    return "\n".join(L)


def write_jsonl(df: pd.DataFrame, path: Path) -> None:
    df.to_json(path, orient="records", lines=True, force_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=str(ROOT / "logs" / "correctness"))
    ap.add_argument("--out", default=None, help="default: results/<date of the first log>-correctness/")
    ap.add_argument("--trace-id", default=None, help="question for failing_trace.md (default: lowest pass rate)")
    a = ap.parse_args()
    df = rows(Path(a.log_dir))
    run_date = min(pd.to_datetime(df.created, utc=True)).tz_convert("America/Vancouver").date()  # course time zone
    out = Path(a.out or ROOT / "results" / f"{run_date}-correctness")
    out.mkdir(parents=True, exist_ok=True)
    meta = {q["id"]: q for q in load()}
    df["config"] = pd.Categorical(df.config, ["baseline", "fixed"], ordered=True)
    df = df.sort_values(["config", "model", "id", "epoch"]).assign(config=lambda d: d.config.astype(str))
    summ = summary(df)
    write_jsonl(summ, out / "summary.jsonl")
    write_jsonl(per_question(df).reset_index(), out / "per_question.jsonl")
    write_jsonl(df.drop(columns=["scores"]), out / "samples.jsonl")
    (out / "failing_trace.md").write_text(failing_trace(df, meta, a.trace_id))
    print(summ.to_string(index=False))
    print(f"total ${summ['cost USD'].sum():.4f} -> {out}")


if __name__ == "__main__":
    main()
