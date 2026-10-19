"""The catalogue: every action there is, found by id (ADR-0068 decision 6)."""

from collections.abc import Iterable, Iterator

from wasifyai_platform_sdk.actions.model import Action, Surface


class ActionRegistry:
    def __init__(self, actions: Iterable[Action] = ()):
        self._actions: dict[str, Action] = {}
        for a in actions:
            self.add(a)

    def add(self, action: Action) -> None:
        if action.id in self._actions:
            raise ValueError(f"action {action.id!r} is already registered")
        self._actions[action.id] = action

    def add_all(self, actions: Iterable[Action]) -> None:
        for a in actions:
            self.add(a)

    def get(self, action_id: str) -> Action | None:
        return self._actions.get(action_id)

    def all(self) -> list[Action]:
        return sorted(self._actions.values(), key=lambda a: a.id)

    def for_surface(self, surface: Surface) -> list[Action]:
        """What may be offered on a surface: the allow-list, never a default (ADR-0057)."""
        return [a for a in self.all() if surface in a.surfaces]

    def __iter__(self) -> Iterator[Action]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._actions)

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._actions
