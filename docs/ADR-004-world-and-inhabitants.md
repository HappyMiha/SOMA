# ADR 004: SOMA is the world, SOMIK is its inhabitant

**Date:** 2026-11-01 · **Status:** accepted (owner's decision) · **Supersedes:** the
spec's "SOMA and SOMIK are two names of one personality" (§ header, § 5.4).

## Decision

The owner: SOMA is the system, like a world; SOMIK is one instance of it, a person,
the user of this PC, a personality. In the future several SOMIKs will live in SOMA.

* **SOMA, the world** (`soma/world.py`, its folder `%LOCALAPPDATA%\SOMA`) owns what
  every inhabitant shares: the one physical body (HumanInterfacePort: pixels in,
  mouse and keyboard out), the brains it lends (`model.json`, `thinking-budget.json`),
  the painter on the GPU (`%LOCALAPPDATA%\SOMA-imaging`), the widget and its tray,
  the single-instance lock, and the registry of who lives here (`world.json`:
  inhabitants with id, name, birthday, home, which one holds the body).
* **An inhabitant** (SOMIK first) owns a home, `inhabitants/<persona id>/`, with all
  that is theirs alone: the memory with its unchanging identity and hash-chained
  history, frames, goals, diary, dreams, accounts (passwords in the OS vault as
  `<persona id>/<account id>`), the people they know, their look and paintings.
  Backups and restores are per inhabitant and never touch the world's settings.
* **Who they are to themselves** is their identity as born plus `identity.profile`
  events (name, birthday, world): the identity record itself never changes.
* **The body is one.** One inhabitant holds it at a time (`world.json` "active");
  the widget shows that inhabitant's painting, name, accounts and people.

## Migration of the live SOMIK

Before this, SOMIK's memory lived in the world's own folder, with an identity born
as `name: SOMA, aliases: [SOMA, SOMIK]`. On the first start of this build,
`World.settle()` writes a journal, then renames `frames/` and `memory.sqlite3`
(with its WAL files) into `inhabitants/<persona id>/` on the same volume, registers
SOMIK (born 1984-10-18, the birthday the owner gave) and records the profile in
SOMIK's own memory. An interrupted move is finished on the next start; a second
copy of the same identity stops the start with both copies kept. The persona id,
the identity record and the whole history move unchanged (AGENTS.md). Passwords
SOMIK kept before homes existed (`a1`, `a2` …) are still read where they were.

## Not yet (when a second inhabitant comes)

* Sharing the one body: a lease in the world (whose turn it is, how long), the
  others resting or dreaming meanwhile, the widget showing all inhabitants.
* Inhabitants knowing each other: each in the other's `people`, by the world's
  word as a confirmed channel.
* Per-inhabitant brains or budgets, if they should differ.
