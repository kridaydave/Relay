# Documentation Consolidation Design: GSD to Normal

**Date:** 2026-05-18
**Status:** Approved

## 1. Goal
Convert all GSD (Get Shit Done) related artifacts into standard project documentation, preserving technical depth while removing workflow-specific jargon and metadata. Consolidate overlapping information into existing core documents.

## 2. Technical Merge
Existing documents in `docs/` will be expanded with details from `docs/`.

### 2.1 `docs/Relay Design Document.md`
Append or integrate the following sections:
- **Component Structure:** Detailed breakdown of the file system and module responsibilities (from `docs/STRUCTURE.md`).
- **External Integrations:** How Relay interacts with LLM providers, frameworks, and storage backends (from `docs/INTEGRATIONS.md`).
- **Data Flow Details:** Expanded explanation of the internal state transitions and signing logic (from `docs/ARCHITECTURE.md`).

### 2.2 `docs/Relay Coding Rules.md`
Append or integrate the following sections:
- **Testing Standards:** Requirements for unit, integration, and parallel test coverage (from `docs/TESTING.md`).
- **Tech Stack:** Justification for Pydantic, HMAC, and other core dependencies (from `docs/STACK.md`).
- **Constraints & Concerns:** Documentation of known architectural limitations and "non-goals" (from `docs/CONCERNS.md`).

## 3. Project Management Relocation
Move the following files to the `docs/` root and remove GSD-specific command references (e.g., `/gsd-plan-phase`):
- `docs/ROADMAP.md` -> `docs/ROADMAP.md`
- `docs/REQUIREMENTS.md` -> `docs/REQUIREMENTS.md`

## 4. Audits & Research Organization
Create dedicated subdirectories for historical context and deep-dives.

### 4.1 `docs/audits/`
Move and rename files from `docs/audits/`:
- `docs/audits/INTEGRATION.md` -> `docs/audits/2026-05-17-integration-audit.md`
- `docs/audits/REVIEW.md` -> `docs/audits/2026-05-17-code-review.md`
- `docs/audits/SECURITY.md` -> `docs/audits/2026-05-17-security-audit.md`
- `docs/audits/REVIEW-FIX.md` -> `docs/audits/2026-05-17-review-fix-log.md`

Remove GSD headers (e.g., `phase: code-review`, `Fixer: gsd-code-fixer`).

### 4.2 `docs/research/`
Move files from `docs/research/` to `docs/research/`:
- `ARCHITECTURE.md` -> `docs/research/architecture-deep-dive.md`
- `PITFALLS.md` -> `docs/research/implementation-pitfalls.md`
- `FEATURES.md` -> `docs/research/feature-explainer.md`
- `SUMMARY.md` -> `docs/research/research-summary.md`

Remove GSD-specific research recommendations and commands.

## 5. Final Cleanup
1. Delete the `.planning/` directory.
2. Delete the `docs/audits/` directory.
3. Update any internal links in the moved files to point to their new locations.
