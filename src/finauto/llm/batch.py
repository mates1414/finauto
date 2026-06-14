"""Provider-aware batch submission for non-interactive jobs (Phase 3, A6).

For bulk, latency-tolerant work (e.g. an overnight queue of report generations),
the Anthropic Batch API runs the same Messages requests asynchronously at **50%
of standard token price**. This module wraps that path behind a tiny,
provider-neutral job shape so a backend can route batch-eligible stages here
while the CLI keeps the synchronous path.

Prompt/context caching: pass a large stable `system` and the API caches it
(Anthropic `cache_control`) — reads bill at ~0.1x. We mark the system block
ephemeral so repeated jobs in a batch share the cached prefix.

Gemini batch mode is provider-specific and not wired here yet; submit those
stages synchronously or extend this module with a `GeminiBatch` path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import Settings


@dataclass
class BatchJob:
    """One batched generation request. `custom_id` correlates job -> result."""

    custom_id: str
    user: str
    system: Optional[str] = None
    max_tokens: int = 8000


class BatchError(Exception):
    pass


def submit_batch(
    jobs: list[BatchJob], settings: Settings, *, stage: str = "report"
) -> str:
    """Submit jobs as an Anthropic message batch; returns the batch id.

    Routes the model from the given stage's config. Only the Anthropic provider
    supports batching here; other providers raise with guidance.
    """
    provider, model = settings.stage(stage)  # type: ignore[arg-type]
    if provider != "claude":
        raise BatchError(
            f"batch submission is only wired for the Anthropic provider; stage "
            f"'{stage}' is routed to '{provider}'. Set FINAUTO_{stage.upper()}_PROVIDER=claude "
            "or submit this stage synchronously."
        )
    try:
        import anthropic
        from anthropic.types.message_create_params import (
            MessageCreateParamsNonStreaming,
        )
        from anthropic.types.messages.batch_create_params import Request
    except ImportError as e:
        raise BatchError(
            "anthropic is not installed; run: pip install finauto[llm]"
        ) from e

    client = anthropic.Anthropic()
    requests: list[Request] = []
    for job in jobs:
        params: dict = {
            "model": model,
            "max_tokens": job.max_tokens,
            "messages": [{"role": "user", "content": job.user}],
        }
        if job.system:
            # Cache the stable system prefix so repeated jobs read it at ~0.1x.
            params["system"] = [
                {
                    "type": "text",
                    "text": job.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        requests.append(
            Request(
                custom_id=job.custom_id,
                params=MessageCreateParamsNonStreaming(**params),
            )
        )
    batch = client.messages.batches.create(requests=requests)
    return batch.id


def fetch_results(batch_id: str, settings: Settings) -> dict[str, str]:
    """Fetch a completed batch's text results, keyed by `custom_id`.

    Returns only succeeded results; raises if the batch has not ended yet.
    """
    try:
        import anthropic
    except ImportError as e:
        raise BatchError(
            "anthropic is not installed; run: pip install finauto[llm]"
        ) from e

    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        raise BatchError(
            f"batch {batch_id} not finished (status={batch.processing_status})"
        )

    out: dict[str, str] = {}
    for result in client.messages.batches.results(batch_id):
        if result.result.type == "succeeded":
            msg = result.result.message
            out[result.custom_id] = "".join(
                b.text for b in msg.content if b.type == "text"
            )
    return out
