"""inspect logs of the ablation -> results/<date>-sql-adherence/: samples.jsonl, summary.jsonl, repairs.jsonl.

    uv run python -m evals.sql_adherence.report [--log-dir logs/sql_adherence] [--out results/...]

summary: one row per model and variant. Rates are over all answers (12 questions x 3 epochs). Extra tokens are
the variant's mean tokens per answer minus the baseline's, for the same model. repairs: every answer the repair step
changed, with the SQL before and after, what DuckDB returned for each, and the reference."""

from __future__ import annotations

import argparse
import math
import statistics
from pathlib import Path

import pandas as pd
from inspect_ai.log import list_eval_logs, read_eval_log

from evals.correctness.build_questions import load
from evals.correctness.checks import execute
from evals.correctness.report import LABEL, cost, rows
from evals.sql_adherence.task import VARIANTS

ROOT = Path(__file__).resolve().parents[2]


def samples(log_dir: Path) -> pd.DataFrame:
    df = rows(log_dir)
    extra = {}
    for info in list_eval_logs(str(log_dir)):
        log = read_eval_log(info.name)
        for s in log.samples or []:
            st = s.store or {}
            extra[(Path(info.name).name, s.id, s.epoch)] = dict(
                validator_retries=st.get("validator_retries", 0), validation_error=st.get("validation_error"),
                second_error=st.get("second_error"), first_text=st.get("first_text"),
                second_text=st.get("second_text"), repairs=st.get("repairs") or [])
    ex = pd.DataFrame([extra[(r.log, r.id, r.epoch)] for r in df.itertuples()], index=df.index)
    return pd.concat([df.drop(columns=["scores"]), ex], axis=1)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    base_tok = {m: (g.tokens_in + g.tokens_out).mean() for m, g in df[df.config == "baseline"].groupby("model")}
    for (m, v), g in df.groupby(["model", "config"]):
        tok = (g.tokens_in + g.tokens_out).mean()
        out.append({
            "model": m, "label": LABEL.get(m, m), "variant": v, "answers": len(g),
            "SQL error rate": round((g.outcome == "SQL error").mean(), 3),
            "schema failure rate": round((g.outcome == "schema failure").mean(), 3),
            "value-correct rate": round((g.outcome == "pass").mean(), 3),
            "retries used": int(g.validator_retries.sum()),
            "repairs applied": int((g.repairs.map(len) > 0).sum()),
            "extra tokens per answer": round(tok - base_tok.get(m, tok), 1),
            "cost USD": round(cost(m, g.tokens_in.sum(), g.tokens_cached.sum(), g.tokens_out.sum()), 4),
            "median latency s": round(statistics.median(g.latency_s.dropna()), 2),
        })
    s = pd.DataFrame(out)
    s["variant"] = pd.Categorical(s.variant, VARIANTS, ordered=True)
    return s.sort_values(["variant", "model"]).assign(variant=lambda d: d.variant.astype(str))


def _value(sql: str):
    try:
        cols, rows_ = execute(sql)
        return float(rows_[0][0]) if rows_ and cols else None, None
    except Exception as e:
        return None, str(e)[:200]


def repairs(df: pd.DataFrame) -> pd.DataFrame:
    ref = {q["id"]: q for q in load()}
    out = []
    for r in df[df.repairs.map(len) > 0].itertuples():
        first, last = r.repairs[0]["before"], r.repairs[-1]["after"]
        v_before, e_before = _value(first)
        v_after, e_after = _value(last)
        q = ref[r.id]
        out.append(dict(model=r.model, variant=r.config, id=r.id, epoch=r.epoch, steps=[c["step"] for c in r.repairs],
                        sql_before=first, sql_after=last, ran_before=e_before is None, value_before=v_before,
                        value_after=v_after, error_after=e_after, reference=q["reference_value"], outcome=r.outcome,
                        changed_value=(e_before is None and not (v_before is not None and v_after is not None
                                                                 and math.isclose(v_before, v_after, rel_tol=1e-9))),
                        wrong_after_repair=r.outcome == "value mismatch"))
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=str(ROOT / "logs" / "sql_adherence"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    df = samples(Path(a.log_dir))
    run_date = min(pd.to_datetime(df.created, utc=True)).tz_convert("America/Vancouver").date()
    out = Path(a.out or ROOT / "results" / f"{run_date}-sql-adherence")
    out.mkdir(parents=True, exist_ok=True)
    df.to_json(out / "samples.jsonl", orient="records", lines=True, force_ascii=False)
    s = summary(df)
    s.to_json(out / "summary.jsonl", orient="records", lines=True, force_ascii=False)
    rp = repairs(df)
    rp.to_json(out / "repairs.jsonl", orient="records", lines=True, force_ascii=False)
    print(s.drop(columns=["label"]).to_string(index=False))
    print(f"total ${s['cost USD'].sum():.4f}, {len(rp)} repaired answers -> {out}")


if __name__ == "__main__":
    main()
