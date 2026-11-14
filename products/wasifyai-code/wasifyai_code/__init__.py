"""wasifyai-code: the coding agent's product (ADR-0101 to ADR-0105).

What is here is the part that needs no screen and no running engine: the interface to the place a
session runs in (`place`), the rows (`store`), the check and the implement, check, fix loop
(`checks`, `loop`), checkpoints and undo (`checkpoints`) and the scheduler (`schedules`). Nothing
here is wired into the app yet: there is no `register`, no action and no route
(`docs/spikes/coding-cores.md` says what is built and what is not)."""

PRODUCT_ID = "wasifyai-code"
