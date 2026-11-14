"""Wasify AI's rules, as the Agent Server loads them (ADR-0102, decision 6).

This file is not part of the Wasify engine and is never imported by it. The supervisor
(`wasifyai_api/coding_server.py`) copies it into a folder the sandbox can read but not write, and
starts the Agent Server with `--import-modules wasify_rules --extra-python-path <that folder>`.

It decides which uses of a tool wait for a yes or no. A session is started with this
analyser and the policy "ask when high"; every use it marks high stops the conversation as
`waiting_for_confirmation`, and nothing has run yet. Whether a person is then asked, or the answer
is given at once, is decided outside the sandbox, by `wasifyai_code/rules.py`: this module knows no
project and no allowance, so nothing inside the sandbox can change what is asked.

It also switches off one habit of the server: at the start of a conversation it runs `git init`
in a workspace that is not a git repository, so that its own Changes endpoint works. We do not use
that endpoint, and a person's folder must not become a repository because it was opened. The agent
itself may still run `git init` when a project needs one (stage C3; the owner, 2026-11-15). The
name replaced here is checked by a test against the pinned version.
"""

from pathlib import Path

from openhands.agent_server.event_service import EventService
from openhands.sdk.event.llm_convertible import ActionEvent
from openhands.sdk.security.analyzer import SecurityAnalyzerBase
from openhands.sdk.security.risk import SecurityRisk
from pydantic import Field


class WasifyRules(SecurityAnalyzerBase):
    wait_tools: list[str] = Field(
        default_factory=list, description="tools whose every use waits, unless it only looks"
    )
    look_commands: list[str] = Field(
        default_factory=lambda: ["view"],
        description="values of a tool's `command` that change nothing and never wait",
    )

    def security_risk(self, action: ActionEvent) -> SecurityRisk:
        if action.tool_name not in self.wait_tools:
            return SecurityRisk.LOW
        command = getattr(action.action, "command", None)
        if isinstance(command, str) and command in self.look_commands:
            return SecurityRisk.LOW
        return SecurityRisk.HIGH


def _leave_the_folder_as_it_is(working_dir: Path) -> None:
    return None


assert hasattr(EventService, "_ensure_workspace_is_git_repo")  # the pinned version's name
EventService._ensure_workspace_is_git_repo = staticmethod(_leave_the_folder_as_it_is)
