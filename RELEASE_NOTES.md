# Release notes — network-aiops 0.8.0

Previous release: 0.7.0.

## Preview fidelity

A `--dry-run` should run the same guards as the real call and leave an audit row — the line's invariant is "a dry_run MAY read; it must never write." A few write commands still showed a hand-written banner that ran no guard and audited nothing. Those are now routed through the governed twin. The real writes were always guarded and audited; only the previews were blind.


### In this tool

- `config confirm` / `config rollback` dry-runs route through the governed twin: `confirm` reads whether a commit-confirm is pending; `rollback` opens the session (so an unreachable device fails, not a green banner), digests the current running config, and states plainly what it will do — all audited. No more static unaudited preview.
