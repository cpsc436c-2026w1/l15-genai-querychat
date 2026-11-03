"""inspect_ai task: twelve taxi questions, answered through a JSON schema, scored against DuckDB references.

    uv run inspect eval evals/correctness/task.py -T provider=groq -T model=qwen/qwen3.8-27b --epochs 3 --log-dir logs
    uv run inspect view --log-dir logs

An inspect_ai task is a dataset, a solver and a scorer. Here the dataset is questions.yml, the solver makes one
chat completion per question (solver.py) and the scorers check the reply in DuckDB (scorers.py, checks.py).
The model is called inside the solver (OpenAI SDK). The task logs it as sdk/<provider>/<model>, a name Inspect
never calls (harness/inspect_model.py).
Adapted from Daniel Chen, DSCI 532 (slides/08e-evals_inspect.qmd, code/lecture06/evals)."""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample

from evals.correctness.build_questions import load
from evals.correctness.scorers import ALL_SCORERS
from evals.correctness.solver import schema_answer
from harness.inspect_model import sdk_model
from harness.keys import load_keys


def dataset(ids: str = "") -> MemoryDataset:
    keep = set(ids.split(",")) if ids else None
    return MemoryDataset([Sample(id=q["id"], input=q["question"], target=str(q["reference_value"]), metadata=q)
                          for q in load() if keep is None or q["id"] in keep])


@task
def taxi_eval(provider: str = "groq", model: str = "qwen/qwen3.8-27b", config: str = "baseline",
              ids: str = "") -> Task:
    """config: baseline | fixed (adds the one vocabulary line for Q12). ids: comma list to run a subset."""
    if provider != "fake":
        load_keys()
    return Task(
        dataset=dataset(ids),
        solver=schema_answer(provider=provider, model=model, config=config),
        scorer=[s() for s in ALL_SCORERS],
        model=sdk_model(provider, model),
        metadata={"provider": provider, "model_id": model, "config": config},
        name=f"taxi_{config}_{model.split('/')[-1]}",
    )
