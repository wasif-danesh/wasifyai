"""Runs the products' model checks against a candidate model (ADR-0025).

A product registers a check for a capability whose model must be vetted (the guardrail's
`text.moderate`). Before an admin can point an alias at a new model, every check for a capability
bound to that alias runs with the capability pointed at the candidate."""

import logging
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from wasifyai_platform_sdk import (
    GraphRegistry,
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    build_capabilities,
    load_product_config,
    reset_context,
    set_context,
)

log = logging.getLogger(__name__)


class RegistryCheckRunner:
    def __init__(self, registry: GraphRegistry, products_dir: Path, deps: ProviderDeps, env: str):
        self._registry = registry
        self._dir = products_dir
        # checks must not write billing usage events
        self._deps = replace(deps, usage=InMemoryUsageRecorder())
        self._env = env

    async def run(self, alias: str, candidate: str) -> list[str]:
        failures: list[str] = []
        for (product_id, capability), check in self._registry.checks().items():
            config = load_product_config(self._dir, product_id, env=self._env)
            binding = config.capabilities.get(capability)
            if binding is None or binding.model != alias:
                continue
            patched = config.model_copy(
                update={
                    "capabilities": {
                        **config.capabilities,
                        capability: binding.model_copy(update={"model": candidate}),
                    }
                }
            )
            caps = build_capabilities(patched, self._deps)
            token = set_context(RunContext("admin", product_id, "admin-check", str(uuid4())))
            try:
                result = await check(caps)
            except Exception as exc:  # a crashing check is a failed check
                log.exception("model check crashed for %s/%s", product_id, capability)
                failures.append(
                    f"{product_id} {capability}: the check crashed ({type(exc).__name__})"
                )
                continue
            finally:
                reset_context(token)
            if not result.passed:
                failures += [f"{product_id} {capability}: {f}" for f in result.failures] or [
                    f"{product_id} {capability}: the check did not pass"
                ]
        return failures
