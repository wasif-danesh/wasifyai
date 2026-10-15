"""ComfyUI workflows and their map files. Only the map file knows node IDs.

See docs/configuration.md."""

import copy
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class WorkflowInput(BaseModel):
    node: str
    field: str


class WorkflowOutput(BaseModel):
    node: str
    type: str


class LoraTarget(BaseModel):
    node: str
    field: str


class LoraChain(BaseModel):
    """Where the model flows, so LoRA loader nodes can be spliced in (ADR-0051 decision 2)."""

    loader: str = "LoraLoaderModelOnly"
    max: int = Field(default=3, ge=1, le=8)
    # the model before any LoRA: `node` (and which of its outputs)
    source: dict[str, Any] = Field(alias="from")
    to: list[LoraTarget]

    model_config = {"populate_by_name": True}


class WorkflowMap(BaseModel):
    workflow: str
    licence: str | None = None
    notes: str | None = None
    models: list[str] = Field(default_factory=list)
    # One input may drive several nodes (e.g. a duration read by both the encoder and the latent):
    # give a list of {node, field} targets.
    inputs: dict[str, WorkflowInput | list[WorkflowInput]]
    outputs: dict[str, WorkflowOutput] = Field(default_factory=dict)
    # absent: this workflow accepts no LoRAs
    lora_chain: LoraChain | None = None

    def targets(self, name: str) -> list[WorkflowInput]:
        v = self.inputs[name]
        return v if isinstance(v, list) else [v]


class Workflow:
    def __init__(self, name: str, graph: dict[str, Any], mapping: WorkflowMap):
        self.name = name
        self.graph = graph
        self.map = mapping

    @classmethod
    def load(cls, workflows_dir: Path, name: str) -> "Workflow":
        map_path = workflows_dir / f"{name}.map.yaml"
        mapping = WorkflowMap.model_validate(yaml.safe_load(map_path.read_text()))
        graph = json.loads((workflows_dir / mapping.workflow).read_text())
        return cls(name, graph, mapping)

    def problems(self) -> list[str]:
        """Every mapped node ID must exist in the workflow JSON."""
        out = []
        for name in self.map.inputs:
            for i in self.map.targets(name):
                if i.node not in self.graph:
                    out.append(f"{self.name}: input {name!r} maps to missing node {i.node!r}")
        for name, o in self.map.outputs.items():
            if o.node not in self.graph:
                out.append(f"{self.name}: output {name!r} maps to missing node {o.node!r}")
        chain = self.map.lora_chain
        if chain is not None:
            if "Lora" not in chain.loader:
                out.append(f"{self.name}: lora_chain loader {chain.loader!r} is not a LoRA loader")
            if str(chain.source.get("node")) not in self.graph:
                out.append(
                    f"{self.name}: lora_chain starts at missing node {chain.source.get('node')!r}"
                )
            for t in chain.to:
                if t.node not in self.graph:
                    out.append(f"{self.name}: lora_chain ends at missing node {t.node!r}")
        return out

    @property
    def accepts_loras(self) -> bool:
        return self.map.lora_chain is not None

    def fill(
        self, values: dict[str, Any], loras: list[tuple[str, float]] | None = None
    ) -> dict[str, Any]:
        unknown = set(values) - set(self.map.inputs)
        if unknown:
            raise ValueError(
                f"workflow {self.name!r} has no input(s) {sorted(unknown)}; "
                f"known: {sorted(self.map.inputs)}"
            )
        graph = copy.deepcopy(self.graph)
        for name, value in values.items():
            for m in self.map.targets(name):
                graph[m.node].setdefault("inputs", {})[m.field] = value
        if loras:
            self._splice_loras(graph, loras)
        return graph

    def _splice_loras(self, graph: dict[str, Any], loras: list[tuple[str, float]]) -> None:
        """`from -> lora_1 -> ... -> lora_n -> to`; new nodes get ids above the highest number."""
        chain = self.map.lora_chain
        if chain is None:
            raise ValueError(f"workflow {self.name!r} does not take LoRAs")
        if len(loras) > chain.max:
            raise ValueError(f"workflow {self.name!r} takes at most {chain.max} LoRAs")
        next_id = max((int(k) for k in graph if str(k).isdigit()), default=0)
        source_node = str(chain.source["node"])
        previous = [source_node, int(chain.source.get("output", 0))]
        for file, weight in loras:
            next_id += 1
            node_id = str(next_id)
            graph[node_id] = {
                "class_type": chain.loader,
                "inputs": {
                    "model": previous,
                    "lora_name": file,
                    "strength_model": weight,
                },
            }
            previous = [node_id, 0]
        for t in chain.to:
            graph[t.node].setdefault("inputs", {})[t.field] = previous


def workflow_problems(workflows_dir: Path, name: str) -> list[str]:
    """Why a configured workflow cannot be loaded; empty when it is fine."""
    map_path = workflows_dir / f"{name}.map.yaml"
    if not map_path.is_file():
        return [f"workflow map not found: {map_path}"]
    try:
        wf = Workflow.load(workflows_dir, name)
    except FileNotFoundError as e:
        return [f"workflow file not found: {e.filename}"]
    except Exception as e:
        return [f"workflow {name!r} is invalid: {e}"]
    return wf.problems()
