# Phase 1: SnapshotStore Protocol Extraction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-17
**Phase:** 1-SnapshotStore Protocol Extraction
**Areas discussed:** Protocol surface, File organization, Pipeline wiring, InMemory store location, close() method

---

## Protocol Surface (Methods)

| Option | Description | Selected |
|--------|-------------|----------|
| All 4 public methods | save_snapshot(), load_snapshot(), get_latest_snapshot(), list_snapshots() — full public surface | |
| Minimal: save + load | Only save_snapshot() and load_snapshot() | |
| Minimal + close() | save_snapshot() + load_snapshot() + close() | |
| Include everything (follow-up) | All 4 public methods + close() | ✓ |

**User's choice:** "Include everything" — all 4 public methods plus close() included in Protocol.

## File Organization

| Option | Description | Selected |
|--------|-------------|----------|
| Same file | Protocol + LocalFileSnapshotStore in snapshot.py | |
| Separate files | Protocol in its own file, LocalFileSnapshotStore in snapshot.py | ✓ |

**User's choice:** Separate files — Protocol in its own file.

## Pipeline Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Optional field (Recommended) | Add snapshot_store as optional param — defaults to LocalFileSnapshotStore if not provided | ✓ |
| Always require | Remove storage_path, callers must provide store | |
| Keep default + setter | Keep current, add method to swap store later | |

**User's choice:** Optional field parameter, following existing pattern.

## InMemorySnapshotStore Location

| Option | Description | Selected |
|--------|-------------|----------|
| Main package (Recommended) | In src/relay/ for community use | ✓ |
| tests/conftest.py | Internal test double only | |

**User's choice:** Main package so Relay users can use it in their own tests.

## close() Method

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include close() | Standard cleanup method | ✓ |
| No, skip close() | Keep minimal | |

**User's choice:** Include close() for future backend cleanup.

## the agent's Discretion

None — all decisions discussed and resolved.

## Deferred Ideas

None.
