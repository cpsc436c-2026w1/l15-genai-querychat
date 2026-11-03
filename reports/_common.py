"""Helpers shared by the report pages: read the raw results, format tables."""
from pathlib import Path

import pandas as pd
from IPython.display import Markdown

RESULTS = Path(__file__).resolve().parent.parent / "results"
LABEL = {"qwen/qwen3.8-27b": "Qwen 3.8 27B (Groq)", "gpt-5.4-nano": "GPT-5.4 nano (OpenAI)",
         "gpt-5.4-mini": "GPT-5.4 mini (OpenAI)"}
SHORT = {"qwen/qwen3.8-27b": "Qwen 3.8 27B", "gpt-5.4-nano": "GPT-5.4 nano", "gpt-5.4-mini": "GPT-5.4 mini"}
ORDER = ["qwen/qwen3.8-27b", "gpt-5.4-nano", "gpt-5.4-mini"]


def jsonl(run: str, name: str) -> pd.DataFrame:
    return pd.read_json(RESULTS / run / name, lines=True, precise_float=True, dtype=False)


def table(df: pd.DataFrame, **kw) -> Markdown:
    return Markdown(df.to_markdown(index=False, **kw))


def usd(x: float, digits: int = 4) -> str:
    return f"${x:,.{digits}f}"

GH = "https://github.com/cpsc436c-2026w1/l15-genai-querychat"


def gh(path: str) -> str:
    """GitHub URL of a repo file (blob) or folder (tree, when the path ends in /)."""
    kind = "tree" if path.endswith("/") else "blob"
    return f"{GH}/{kind}/main/{path.rstrip('/')}"


def links(paths, base: str = "") -> str:
    """Markdown links to repo paths, labelled by their last part."""
    out = []
    for p in paths:
        full = base + p
        label = p.rstrip("/").split("/")[-1] + ("/" if p.endswith("/") else "")
        out.append(f"[{label}]({gh(full)})")
    return ", ".join(out)


def sources(raw: dict, code: dict, viewer: str | None = None) -> str:
    """The Sources block: raw outputs and the files that define the eval, as two short lines."""
    lines = ["**Sources.** Raw outputs: " + " · ".join(f"`{d}`: {links(fs, d)}" for d, fs in raw.items()) + "."]
    lines.append("Eval files: " + " · ".join(f"`{d}`: {links(fs, d)}" for d, fs in code.items()) + "."
                 + (f" [Open the runs]({viewer}) in the Inspect log viewer." if viewer else ""))
    return "\n\n".join(lines)
