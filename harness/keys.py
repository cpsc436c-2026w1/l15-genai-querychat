"""API keys from the environment, or from a `.env` file at the repo root. Values are never printed or written.

    cp .env.example .env      # then put your own keys in .env (it is gitignored)

A key already set in the environment wins over the file. Only the provider you call needs a key."""

from __future__ import annotations

import os

from harness import ROOT

NAMES = ("GROQ_API_KEY", "OPENAI_API_KEY")


def load_keys(env_file=ROOT / ".env") -> list[str]:
    """Read KEY=VALUE lines of `.env` into the environment; return the names now set (never the values)."""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k in NAMES and v and not os.environ.get(k):
                os.environ[k] = v
    return [n for n in NAMES if os.environ.get(n)]


def require(name: str) -> str:
    if not os.environ.get(name):
        load_keys()
    if not os.environ.get(name):
        raise SystemExit(f"{name} is not set: copy .env.example to .env and add your key (see README.md)")
    return os.environ[name]


if __name__ == "__main__":
    print("keys set:", load_keys())
