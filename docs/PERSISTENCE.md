# Memory and recovery contract

`MemoryStore(data_dir: Path)` reads and writes only SOMA's selected application data directory. It opens `memory.sqlite3` in SQLite WAL mode with FULL synchronization, verifies SQLite/foreign-key integrity, the event hash chain, checkpoint evidence, persisted identity and retained frame hashes before continuing. It refuses unknown schema versions or damaged history instead of creating a replacement personality. The current schema version is 1; no older deployed schema exists yet.

One immutable identity record contains `persona_id`, the aliases `SOMA` and `SOMIK`, initial traits/motives and creation time. Model configuration is separate from identity. Evolving interests, lessons and current state belong in new memories/checkpoints, preserving the original autobiography.

The public API is:

| Method | Result and durability |
| --- | --- |
| `identity()` | Fresh decoded identity dictionary; callers cannot mutate stored identity by modifying it |
| `append_event(kind, data)` | Committed integer event ID; hashes include previous event, ID, timestamp, kind and canonical JSON |
| `events(limit=30)` | Most recent `limit` events in chronological order, with decoded `data`, `id`, `timestamp`, `kind`, `previous_hash`, `hash` |
| `put_goal(goal)` / `goals()` | Stable goal ID/current projection; each revision remains an event |
| `add_memory(kind, content, source, confidence=0.5)` | New immutable record ID; kinds: episodic, semantic, procedural, social, intentions, reflective |
| `recall(query='', limit=12)` | Decoded memory records with provenance/confidence, using a Unicode case-insensitive token-overlap index; empty query returns recent records |
| `begin_action(action, before_frame_id)` | Commits an intent event and pending journal row in one transaction **before** external input |
| `finish_action(id, outcome, after_frame_id)` | Stores visual outcome. `uncertain` remains unresolved; only success/failure closes the journal entry |
| `pending_actions()` | Pending and uncertain entries, with decoded `action` and `outcome`; never emits/replays input |
| `pending_demonstrations()` | Completed raw episodic traces plus journal-reconstructed interrupted traces, merged by ID; excludes acquired/unusable lessons and never restarts hooks or input |
| `checkpoint(state)` / `latest_checkpoint()` | New checkpoint ID / the stored state dictionary directly (not an envelope), or `None` |
| `save_frame(frame)` | Atomic app-owned PNG path; model-provided filenames are never used |
| `backup(destination)` | Writes a consistent portable ZIP containing a SQLite backup, retained frames and a version/persona manifest |
| `MemoryStore.restore_backup(archive, data_dir)` | Validates and restores a closed store; returns the preserved previous data directory, or `None` for a fresh destination |
| `close()` | Closes the connection; safe to call again |

The store uses one `RLock` and a connection configured for worker/UI access. Writes use `BEGIN IMMEDIATE`; intent, outcome, memory and checkpoint operations commit atomically with their log event. SQLite triggers reject changing/deleting history, memory revisions, checkpoints and identity. These checks detect accidental corruption; hashes without an external trust anchor are not a digital signature against an attacker who can rewrite the entire database.

Screenshot storage defaults to 256 MiB. Pruning removes oldest retained images while preserving before/after frames for unresolved actions; the latest frame is retained. Protected unresolved frames can temporarily exceed the budget, so the kernel must reconcile its journal before generating more actions. Frame metadata and explicit pruning events remain in history. Orphaned app-generated temporary/images from interrupted writes are removed at startup. Event history, goals and memory records are not automatically deleted: autobiography is append-only, so its disk growth must be observed and backed up. Recall currently provides lexical matching, not learned embedding similarity or an evaluated semantic-retrieval guarantee.

Backup exports only known SOMA database/frame records. It does not read arbitrary neighboring files, application databases, credentials from the system keychain, or unrelated files placed in the app directory. Configuration and API keys are not exported; after restore the inference configuration may need to be entered again. A ZIP can contain private screenshots and should be handled as personal data.

Before restore, stop the kernel, wait for its worker, and close the store. The same-process active-store guard enforces this requirement; the caller must also prevent another app process from running against the same directory. Restore rejects duplicate entries, symlinks, traversal, unknown paths, corrupt SQLite, mismatched hashes, unsupported versions and manifest/persona mismatch. It first stages and validates the archive on the same filesystem. The existing directory is renamed to `<data_dir>.before-restore-<uuid>` and is never deleted by restore; the staged directory then takes its place. If the second rename fails, the old directory is put back.

Portable operating systems do not expose one common atomic directory-exchange call. A flushed sibling `.<data_dir-name>.restore-pending.json` therefore records both directory paths before replacement. If power fails between renames, startup detects the marker and refuses to create a new identity. Recover the listed previous or staged directory first, validate it, and clear the marker only once the intended directory is restored. Automatic recovery of this rare interrupted-directory-swap case is not yet a GUI workflow.

Verification: `python -m unittest discover -s tests -p test_memory.py -v` exercises restart/provider continuity, six memory kinds, provenance, real subprocess `os._exit` recovery, transaction rollback, uncertainty reconciliation, concurrent writes, corruption detection, quotas and pending-frame retention, backup/restore continuity, malicious ZIP paths and interrupted-restore refusal. These are local storage tests; they do not certify a physical-PC reboot or full-disk behavior on every filesystem.
