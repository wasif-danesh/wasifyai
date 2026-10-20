"""The action model (ADR-0068 decision 1): what a person or an agent can ask the product to do.

An action is data plus a binding to the code that runs it. The data is what the surfaces read
(the assistant's tools, MCP tools, the help corpus, `docs/contracts/actions.json`); the binding is
only ever called by the executor (`executor.py`)."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, SkipValidation, model_validator

Effect = Literal["read", "make", "change", "destroy"]
Flag = Literal["costly", "leaves_device", "needs_consent", "private"]
Surface = Literal["assistant", "mcp"]
NeedKind = Literal["product", "model", "runtime", "notebooks", "chat", "web"]

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
ORIGIN_PATTERN = re.compile(r"^(window|assistant|mcp:[A-Za-z0-9][A-Za-z0-9 ._-]{0,63})$")
EFFECTS: tuple[str, ...] = ("read", "make", "change", "destroy")
PLATFORM = "platform"  # the product id of actions that belong to no product


def parse_origin(origin: str) -> str:
    """`window`, `assistant`, or `mcp:<connection>`: who is asking. Anything else is a bug."""
    if not ORIGIN_PATTERN.match(origin):
        raise ValueError(f"origin must be window, assistant or mcp:<connection>, not {origin!r}")
    return origin


def surface_of(origin: str) -> Surface | None:
    """The surface an origin comes through (`window` is not one: it is the person)."""
    if origin == "assistant":
        return "assistant"
    if origin.startswith("mcp:"):
        return "mcp"
    return None


class Need(BaseModel):
    """Something that must be ready before an action can run. The host says whether it is:
    `product` (a product is served here), `model` (the model of a task, for example `speak`),
    `runtime` (what runs models, for example `lipsync`), `notebooks`, `chat` (the chat model),
    `web` (web search is allowed by the person and its provider is ready)."""

    model_config = ConfigDict(frozen=True)

    kind: NeedKind
    name: str = ""

    def __str__(self) -> str:
        return f"{self.kind}:{self.name}" if self.name else self.kind


def need_product(name: str) -> Need:
    return Need(kind="product", name=name)


def need_model(task: str) -> Need:
    return Need(kind="model", name=task)


def need_runtime(name: str) -> Need:
    return Need(kind="runtime", name=name)


NOTEBOOKS = Need(kind="notebooks")
CHAT = Need(kind="chat")
WEB = Need(kind="web")


class Readiness(BaseModel):
    """What `requires` resolves to (ADR-0068): ready, needs a step that fixes it, or cannot be
    done here at all."""

    state: Literal["ready", "needs_setup", "unavailable"]
    step: str = ""  # needs_setup: the sentence that fixes it ("Set up the speech models")
    reason: str = ""  # unavailable: why, for a person
    ui: str | None = None  # needs_setup: the screen that fixes it (a menu item id)

    @classmethod
    def ready(cls) -> "Readiness":
        return cls(state="ready")

    @classmethod
    def needs_setup(cls, step: str, ui: str | None = None) -> "Readiness":
        return cls(state="needs_setup", step=step, ui=ui)

    @classmethod
    def unavailable(cls, reason: str) -> "Readiness":
        return cls(state="unavailable", reason=reason)


class ActionRefused(Exception):
    """Raised by an action's check or binding: the request cannot be done as asked. `message` is
    a sentence for the person and the model (the product's own `check_*` sentences)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Outcome:
    """What a binding hands back: the executor turns it into an `ActionResult`."""

    status: Literal["ok", "refused", "error"]
    output: dict[str, Any] = field(default_factory=dict)
    text: str = ""  # for the model: one or two sentences
    code: str = ""

    @classmethod
    def ok(cls, output: dict[str, Any], text: str) -> "Outcome":
        return cls("ok", output, text)

    @classmethod
    def refused(cls, text: str, code: str = "refused") -> "Outcome":
        return cls("refused", {"message": text}, text, code)

    @classmethod
    def error(cls, text: str, code: str = "failed") -> "Outcome":
        return cls("error", {}, text, code)


# async (params, context) -> Outcome; the context is `executor.ActionContext`
Call = Callable[[Any, Any], Awaitable[Outcome]]
# async (params, context) -> None, or raises ActionRefused: the product's own checks, run before
# anything is loaded or queued
Check = Callable[[Any, Any], Awaitable[None]]
# (params, context) -> the graph input of the child run
BuildInput = Callable[[Any, Any], Awaitable[dict[str, Any]] | dict[str, Any]]
# (done outputs, params) -> Outcome, or None when the outputs are not a result
BuildResult = Callable[[dict[str, Any], Any], Outcome | None]


@dataclass(frozen=True)
class RunBinding:
    """The child run of a product graph (ADR-0057): its events, safeguards, quotas and queue are
    the product's own. `noun` makes the sentences ("The image could not be made")."""

    product_id: str
    noun: str
    build_input: BuildInput
    result: BuildResult
    check: Check | None = None


@dataclass(frozen=True)
class CallBinding:
    """A direct function: reads or changes what the engine already holds."""

    call: Call
    check: Check | None = None


Binding = RunBinding | CallBinding


class Action(BaseModel):
    """One thing the product can do. See ADR-0068 decision 1 for the fields."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    title: str
    summary: str  # for people: one line
    description: str  # for a model: when to use it, when not to, what it returns
    input: type[BaseModel]
    output: type[BaseModel]
    examples: tuple[dict[str, Any], ...] = ()
    effect: Effect
    flags: tuple[Flag, ...] = ()
    requires: tuple[Need, ...] = ()
    long: bool = False
    bind: Annotated[Binding, SkipValidation]
    product: str = PLATFORM  # who declares it (and whose usage and audit rows it writes)
    ui: str | None = None  # the menu item that does the same thing
    ui_exempt: str = ""  # when `ui` is None: why (a sentence); every action says one or the other
    surfaces: tuple[Surface, ...] = ("assistant", "mcp")
    consent: str = ""  # needs_consent: the statement the person agrees to

    @model_validator(mode="after")
    def _check(self) -> "Action":
        if not ID_PATTERN.match(self.id):
            raise ValueError(f"action id {self.id!r} must look like domain.verb")
        if "needs_consent" in self.flags and not self.consent:
            raise ValueError(f"{self.id}: a needs_consent action must carry its consent statement")
        if self.consent and "needs_consent" not in self.flags:
            raise ValueError(f"{self.id}: only a needs_consent action carries a consent statement")
        if self.ui is None and not self.ui_exempt:
            raise ValueError(f"{self.id}: give the menu item it matches, or say why it has none")
        if self.ui is not None and self.ui_exempt:
            raise ValueError(f"{self.id}: it has a menu item, so it needs no exemption")
        if len(set(self.flags)) != len(self.flags):
            raise ValueError(f"{self.id}: a flag is listed twice")
        if self.effect == "read" and "needs_consent" in self.flags:
            raise ValueError(f"{self.id}: a read cannot need consent")
        for example in self.examples:
            self.input.model_validate(example)  # an example that does not validate is a bug
        return self

    @property
    def domain(self) -> str:
        return self.id.split(".", 1)[0]

    @property
    def private(self) -> bool:
        return "private" in self.flags
