"""Deterministic providers for tests: no GPU, no network (provider: fake)."""

import hashlib
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.jobs import JobHandle, JobRequest, JobSink
from wasifyai_platform_sdk.parts import Prompt, as_parts, counts
from wasifyai_platform_sdk.usage import (
    EMBEDDING_TOKENS,
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    UsageRecorder,
    record_safely,
)

DEFAULT_REPLY = "Hello from the fake provider."


class FakeTextProvider:
    """Reply text comes from the binding's `defaults.reply`; embeddings are hash-based."""

    def __init__(self, usage: UsageRecorder, dims: int = 768):
        self._usage = usage
        self._dims = dims
        self.prompts: list[Prompt] = []  # what callers sent, for assertions
        self._calls: dict[str, int] = {}

    async def stream(
        self,
        capability: str,
        binding: CapabilityBinding,
        system: str,
        prompt: Prompt,
        schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        ctx = require_context()
        self.prompts.append(prompt)
        reply = self._next_reply(capability, binding)
        words = reply.split(" ")
        for w in words:
            yield w + " "
        meta: dict[str, Any] = {"capability": capability, "alias": binding.model, "estimated": True}
        if media := {k: v for k, v in counts(prompt).items() if v}:
            meta["inputs"] = media
        await record_safely(
            self._usage,
            UsageEvent.for_context(
                ctx,
                LLM_INPUT_TOKENS,
                len((system + " ".join(p for p in as_parts(prompt) if isinstance(p, str))).split()),
                "tokens",
                **meta,
            ),
        )
        await record_safely(
            self._usage,
            UsageEvent.for_context(ctx, LLM_OUTPUT_TOKENS, len(words), "tokens", **meta),
        )

    def _next_reply(self, capability: str, binding: CapabilityBinding) -> str:
        """`defaults.replies` is a script: one reply per call, then the last one repeats.
        `defaults.reply` is a single fixed reply."""
        replies = binding.defaults.get("replies")
        if not replies:
            return str(binding.defaults.get("reply", DEFAULT_REPLY))
        i = self._calls.get(capability, 0)
        self._calls[capability] = i + 1
        return str(replies[min(i, len(replies) - 1)])

    async def embed(
        self, capability: str, binding: CapabilityBinding, texts: list[str]
    ) -> list[list[float]]:
        ctx = require_context()
        await record_safely(
            self._usage,
            UsageEvent.for_context(
                ctx,
                EMBEDDING_TOKENS,
                sum(len(t.split()) for t in texts),
                "tokens",
                capability=capability,
                estimated=True,
            ),
        )
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        # Same text -> same vector; shared words -> similar vectors (bag of hashed words).
        vec = [0.0] * self._dims
        for word in text.lower().split():
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            vec[h % self._dims] += 1.0
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]


class FakeMediaProvider:
    def __init__(self, sink: JobSink | None = None):
        self._sink = sink
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def generate(
        self, capability: str, binding: CapabilityBinding, inputs: dict[str, Any]
    ) -> JobHandle:
        ctx = require_context()
        merged = {**binding.defaults, **inputs}
        self.calls.append((capability, merged))
        job_id = str(uuid4())
        if self._sink is not None:
            await self._sink.submit(
                JobRequest(
                    job_id=job_id,
                    tenant_id=ctx.tenant_id,
                    product_id=ctx.product_id,
                    user_id=ctx.user_id,
                    run_id=ctx.run_id,
                    thread_id=ctx.thread_id,
                    capability=capability,
                    workflow="fake",
                    prompt=merged,
                    outputs={},
                )
            )
        return JobHandle(job_id=job_id, capability=capability)
