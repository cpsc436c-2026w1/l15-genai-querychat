"""The model name Inspect logs for a solver that calls the provider's SDK itself.

The solvers in evals/ call Groq and OpenAI through the OpenAI SDK (harness/llm.py, evals/correctness/solver.py),
so Inspect never sends a request. Giving the task `model=sdk_model("openai", "gpt-5.4-nano")` makes the log, the
run list and the page title show `sdk/openai/gpt-5.4-nano` instead of `mockllm/model`. The `sdk` provider cannot be
called: its generate() raises, so a request from Inspect would fail loudly instead of going anywhere.

`record_usage` adds a sample's tokens to Inspect's usage counters, so the log viewer shows them in its Tokens
columns. It uses Inspect's internal bookkeeping (inspect_ai.model._model), checked against inspect-ai 0.3.287."""

from __future__ import annotations

from inspect_ai.model import GenerateConfig, ModelAPI, ModelUsage, modelapi


class SdkModel(ModelAPI):
    def __init__(self, model_name: str, base_url: str | None = None, api_key: str | None = None,
                 config: GenerateConfig = GenerateConfig(), **model_args) -> None:
        super().__init__(model_name, base_url, api_key, [], config)

    async def generate(self, input, tools, tool_choice, config):
        raise RuntimeError(f"sdk/{self.model_name}: the solver calls this model through the provider's SDK. "
                           "Inspect does not call it")


@modelapi(name="sdk")
def sdk():
    return SdkModel


def sdk_model(provider: str, model: str) -> str:
    return f"sdk/{provider}/{model}"


def record_usage(model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> None:
    """Count one call's tokens for the current sample and the whole run, under the logged model name."""
    from inspect_ai.model._model import model_usage_context_var, sample_model_usage_context_var, set_model_usage

    usage = ModelUsage(input_tokens=tokens_in - tokens_cached, output_tokens=tokens_out,
                       total_tokens=tokens_in + tokens_out, input_tokens_cache_read=tokens_cached or None)
    for var in (sample_model_usage_context_var, model_usage_context_var):
        set_model_usage(model, usage.model_copy(), var.get(None))
