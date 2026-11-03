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
