# Documentation Link Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update all internal documentation links to reflect the new consolidated structure, ensuring cross-references between core docs, research, audits, and history remain functional.

**Architecture:** Use `grep_search` to find all legacy paths and `replace` to update them to the new structure, with special attention to relative paths and specific files like `Internal-changelog.md` and `.planning/STATE.md`.

**Tech Stack:** Markdown, Shell (grep/sed-like operations via tools)

---

### Task 1: Update Top-Level & Internal Changelog Links

**Files:**
- Modify: `Internal-changelog.md`
- Modify: `.planning/STATE.md`

- [ ] **Step 1: Update `Internal-changelog.md`**

Replace legacy paths with new paths.

```markdown
Old: `docs/audits/2026-05-17-full-codebase-review.md`
New: `docs/audits/2026-05-17-full-codebase-review.md`
```

- [ ] **Step 2: Update `.planning/STATE.md`**

Even though `.planning/` is targeted for deletion, `STATE.md` might persist for a while or be used by agents. Update its internal references.

```markdown
Old: `docs/project-overview.md` -> New: `docs/project-overview.md`
Old: `docs/REQUIREMENTS.md` -> New: `docs/REQUIREMENTS.md`
Old: `docs/ROADMAP.md` -> New: `docs/ROADMAP.md`
Old: `docs/` -> New: (integrated into Design Doc / Coding Rules)
Old: `docs/research/` -> New: `docs/research/`
Old: `docs/history/` -> New: `docs/history/phases/`
```

- [ ] **Step 3: Commit top-level link updates**

---

### Task 2: Update Research & Audit Documentation Links

**Files:**
- Modify: `docs/research/*.md`
- Modify: `docs/audits/*.md`
- Modify: `docs/project-overview.md`
- Modify: `docs/Relay Design Document.md`
- Modify: `docs/Relay Coding Rules.md`

- [ ] **Step 1: Update `docs/project-overview.md`**

Update references to legacy `.planning/` files.

- [ ] **Step 2: Update `docs/research/` files**

Update any cross-references that still use `docs/research/`.

- [ ] **Step 3: Update `docs/audits/` files**

Update references to legacy `docs/audits/` and `.planning/` paths.

- [ ] **Step 4: Commit research/audit link updates**

---

### Task 3: Update History/Phases Documentation Links

**Files:**
- Modify: `docs/history/phases/**/*.md`

- [ ] **Step 1: Update Phase 1 Links**

Update links in `docs/history/phases/01-snapshotstore-protocol-extraction/`. These are deep in the directory tree.

```markdown
Old: `docs/REQUIREMENTS.md`
New: `../../../REQUIREMENTS.md` (or similar relative path)
```

- [ ] **Step 2: Update Phase 2 Links**

Update links in `docs/history/phases/02-structured-audit-logging/`.

- [ ] **Step 3: Commit history link updates**

---

### Task 4: Final Verification

- [ ] **Step 1: Run comprehensive grep for legacy paths**

Run: `grep_search -p "\.planning/|docs/audits/" -i "*.md"`
Expected: 0 matches (except perhaps in plans/specs themselves if they reference the migration).

- [ ] **Step 2: Verify key links manually**

Check `Internal-changelog.md` and `docs/ROADMAP.md`.
