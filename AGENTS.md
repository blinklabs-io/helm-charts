# Agent instructions

## Comments

Comments explain an invariant, a non-obvious algorithm, or a gotcha: why this
order, why this bound, why the obvious thing is wrong. Delete comments that
restate the code below them, label sections, or narrate a change's history.
Prose explaining how a system works belongs in documentation.

Documentation comments on exported identifiers are the exception: they are
published API documentation and must remain accurate.

Chart values documentation is the exception. Comments in `values.yaml` and the
values tables in each chart README are the interface consumers read: keep them
accurate.
