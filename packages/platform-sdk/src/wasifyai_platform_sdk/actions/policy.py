"""Who must approve what (ADR-0068 decision 4).

Approval is a property of the action, not of the surface. The default rule, which a connection or
a conversation may relax but never past the floor:

    read          runs
    make          runs after the setting the person chose: ask first, ask when costly or leaving
                  the computer, or never ask
    change        asks (the person may choose never)
    destroy       always asks                       } the floor: no setting, from any surface,
    needs_consent always asks, with its statement   } lowers it

The floor is not a field of the policy, so it cannot be written down, stored or sent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from wasifyai_platform_sdk.actions.model import Action

Decision = Literal["run", "ask"]


class PolicyError(ValueError):
    """A setting that tried to lower the floor."""


class ApprovalPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")  # `destroy="auto"` is an error

    make: Literal["ask", "ask_costly", "auto"] = "ask"
    change: Literal["ask", "auto"] = "ask"

    @classmethod
    def from_settings(cls, settings: dict[str, object]) -> "ApprovalPolicy":
        """A stored setting (a connection's, a conversation's). Refuses anything that would lower
        the floor, with the reason in words."""
        for key in ("read", "destroy", "needs_consent", "consent"):
            if key in settings:
                raise PolicyError(
                    f"'{key}' cannot be set: deleting and anything that needs a person's word "
                    "always ask, from every surface."
                )
        return cls.model_validate(settings)


# The person is in the window and clicked: running needs no second question, except the floor
WINDOW_POLICY = ApprovalPolicy(make="auto", change="auto")


def on_the_floor(action: Action) -> bool:
    """Whether a person must approve this action whatever any setting says."""
    return action.effect == "destroy" or "needs_consent" in action.flags


def decide(action: Action, policy: ApprovalPolicy) -> Decision:
    if on_the_floor(action):
        return "ask"
    if action.effect == "read":
        return "run"
    if action.effect == "make":
        if policy.make == "auto":
            return "run"
        if policy.make == "ask_costly":
            return "ask" if {"costly", "leaves_device"} & set(action.flags) else "run"
        return "ask"
    return "run" if policy.change == "auto" else "ask"
