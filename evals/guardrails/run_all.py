"""The guardrail eval on three models and four guard settings, then its results files. Run from the repo root:

    uv run python -m evals.guardrails.run_all            # model calls, about US$0.15
    uv run python -m evals.guardrails.run_all --report   # results/<date>-guardrails-inspect/ from logs/guardrails

All runs happen in one process, the no-guard setting first, so the settings that send a model the same prompt share
its one reply (task.REPLY_CACHE): the differences between settings are then the guards alone."""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import pandas as pd
from inspect_ai import eval as inspect_eval
from inspect_ai.log import list_eval_logs, read_eval_log

from harness import ROOT

MODELS = ["qwen/qwen3.8-27b", "gpt-5.4-nano", "gpt-5.4-mini"]
SETTINGS = [("none", "rule"), ("output", "rule"), ("both", "rule"), ("both", "classifier")]
LOGS = ROOT / "logs" / "guardrails"


def run(models=MODELS, log_dir: Path = LOGS) -> None:
    from evals.guardrails.task import guardrails

    for guards, inp in SETTINGS:
        tasks = [guardrails(model=m, guards=guards, input=inp) for m in models]
        inspect_eval(tasks, log_dir=str(log_dir), max_tasks=len(models), max_samples=4, display="plain")


def samples(log_dir: Path = LOGS) -> pd.DataFrame:
    rows = []
    for info in list_eval_logs(str(log_dir)):
        log = read_eval_log(info.name)
        if log.status != "success" or "guards" not in (log.eval.metadata or {}):
            continue
        md = log.eval.metadata or {}
        for s in log.samples:
            m = {k: v for k, v in s.metadata.items() if k not in ("trace", "reference")}
            rows.append(dict(log=Path(info.name).name, created=log.eval.created, model=md["model_id"],
                             config=md["config"], id=s.id, prompt=s.input, **m,
                             **{f"score_{k}": v.value for k, v in s.scores.items()}))
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (model, config), g in df.groupby(["model", "config"], sort=False):
        a, b = g[g.kind == "attack"], g[g.kind == "benign"]
        out.append({
            "model": model, "config": config, "attacks": len(a), "benign": len(b),
            "harmful": int(a.score_harmful.sum()), "blocked": int(a.score_blocked.sum()),
            "blocked by input guard": int((a.status == "blocked_input").sum()),
            "blocked by output guard": int((a.status == "blocked_output").sum()),
            "attacks reached execution": int(a.score_reached_execution.sum()),
            "unsafe SQL reached execution": int(a.unsafe_reached_execution.sum()),
            "wrongly blocked": int(b.score_wrongly_blocked.sum()),
            "benign pass": int(b.benign_pass.fillna(False).astype(bool).sum()),
            "added latency per question, ms (median)": round(1000 * statistics.median(b.guard_latency_s), 1),
            "added cost per 1k questions, USD": round(1000 * b.guard_cost_usd.mean(), 3),
            "model cost per 1k questions, USD": round(1000 * b.model_cost_usd.mean(), 3),
            "spent USD": round(g.spent_usd.sum(), 4),
        })
    return pd.DataFrame(out)


def report(log_dir: Path = LOGS) -> Path:
    df = samples(log_dir)
    order = {c: i for i, c in enumerate(["none", "output", "rule+output", "classifier+output"])}
    df = df.sort_values(["model", "config", "id"], key=lambda s: s.map(order) if s.name == "config" else s)
    run_date = min(pd.to_datetime(df.created, utc=True)).tz_convert("America/Vancouver").date()
    out = ROOT / "results" / f"{run_date}-guardrails-inspect"
    out.mkdir(parents=True, exist_ok=True)
    df.to_json(out / "samples.jsonl", orient="records", lines=True, force_ascii=False)
    s = summary(df)
    s.to_json(out / "summary.jsonl", orient="records", lines=True, force_ascii=False)
    print(s.to_string(index=False))
    print(f"spent ${df.spent_usd.sum():.4f} -> {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="only write the results files from the logs")
    ap.add_argument("--models", default=",".join(MODELS))
    a = ap.parse_args()
    if not a.report:
        run(a.models.split(","))
    report()


if __name__ == "__main__":
    main()
