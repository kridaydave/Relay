# Organize Audits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate GSD planning artifacts into standard documentation by moving files from `docs/audits/` to `docs/audits/` and stripping workflow-specific headers.

**Architecture:** Create `docs/audits/`, move files with new names, and use `replace` or `write_file` to remove YAML headers.

**Tech Stack:** Shell commands, Python (for file operations if needed), Markdown.

---

### Task 1: Create Directory and Move Files

**Files:**
- Create: `docs/audits/`
- Move: `docs/audits/INTEGRATION.md` -> `docs/audits/2026-05-17-integration-audit.md`
- Move: `docs/audits/REVIEW.md` -> `docs/audits/2026-05-17-code-review.md`
- Move: `docs/audits/SECURITY.md` -> `docs/audits/2026-05-17-security-audit.md`
- Move: `docs/audits/REVIEW-FIX.md` -> `docs/audits/2026-05-17-review-fix-log.md`

- [ ] **Step 1: Create `docs/audits/` directory**
Run: `mkdir docs/audits/`

- [ ] **Step 2: Move INTEGRATION.md**
Run: `mv docs/audits/INTEGRATION.md docs/audits/2026-05-17-integration-audit.md`

- [ ] **Step 3: Move REVIEW.md**
Run: `mv docs/audits/REVIEW.md docs/audits/2026-05-17-code-review.md`

- [ ] **Step 4: Move SECURITY.md**
Run: `mv docs/audits/SECURITY.md docs/audits/2026-05-17-security-audit.md`

- [ ] **Step 5: Move REVIEW-FIX.md**
Run: `mv docs/audits/REVIEW-FIX.md docs/audits/2026-05-17-review-fix-log.md`

---

### Task 2: Strip YAML Headers

**Files:**
- Modify: `docs/audits/2026-05-17-code-review.md`
- Modify: `docs/audits/2026-05-17-review-fix-log.md`

- [ ] **Step 1: Strip header from `docs/audits/2026-05-17-code-review.md`**
Read the file, identify the `---` fenced YAML block at the top, and remove it.

- [ ] **Step 2: Strip header from `docs/audits/2026-05-17-review-fix-log.md`**
Read the file, identify the `---` fenced YAML block at the top, and remove it.

- [ ] **Step 3: Verify all files in `docs/audits/` have no GSD headers**
Check the first few lines of each file in `docs/audits/`.

---

### Task 3: Cleanup

- [ ] **Step 1: Remove `docs/audits/` if empty**
Run: `rmdir docs/audits/` (only if empty)
