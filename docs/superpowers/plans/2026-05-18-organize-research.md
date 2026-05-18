# Organize Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate research artifacts into standard documentation and remove GSD-specific references.

**Architecture:** Move files from `docs/research/` to `docs/research/` with more descriptive names. Clean the content by removing any references to `/gsd` commands or "Recommendations" sections that are workflow-specific.

**Tech Stack:** Shell commands (mkdir, mv), Text replacement.

---

### Task 1: Create Directory and Move Files

**Files:**
- Create: `docs/research/`
- Move: `docs/research/ARCHITECTURE.md` -> `docs/research/architecture-deep-dive.md`
- Move: `docs/research/PITFALLS.md` -> `docs/research/implementation-pitfalls.md`
- Move: `docs/research/FEATURES.md` -> `docs/research/feature-explainer.md`
- Move: `docs/research/SUMMARY.md` -> `docs/research/research-summary.md`
- Move: `docs/research/STACK.md` -> `docs/research/tech-stack.md`
- Move: `docs/research/PHASE1-EXECUTION-RESEARCH.md` -> `docs/research/phase1-execution-research.md`

- [ ] **Step 1: Create the target directory**

Run: `powershell -NoProfile -Command "mkdir docs/research"`

- [ ] **Step 2: Move ARCHITECTURE.md**

Run: `powershell -NoProfile -Command "mv docs/research/ARCHITECTURE.md docs/research/architecture-deep-dive.md"`

- [ ] **Step 3: Move PITFALLS.md**

Run: `powershell -NoProfile -Command "mv docs/research/PITFALLS.md docs/research/implementation-pitfalls.md"`

- [ ] **Step 4: Move FEATURES.md**

Run: `powershell -NoProfile -Command "mv docs/research/FEATURES.md docs/research/feature-explainer.md"`

- [ ] **Step 5: Move SUMMARY.md**

Run: `powershell -NoProfile -Command "mv docs/research/SUMMARY.md docs/research/research-summary.md"`

- [ ] **Step 6: Move STACK.md**

Run: `powershell -NoProfile -Command "mv docs/research/STACK.md docs/research/tech-stack.md"`

- [ ] **Step 7: Move PHASE1-EXECUTION-RESEARCH.md**

Run: `powershell -NoProfile -Command "mv docs/research/PHASE1-EXECUTION-RESEARCH.md docs/research/phase1-execution-research.md"`

### Task 2: Clean Research Summary

**Files:**
- Modify: `docs/research/research-summary.md`

- [ ] **Step 1: Remove `/gsd` command references and research flags**

Read the file and remove lines containing `/gsd` and any sections titled "Research Flags" if they are purely workflow-oriented.

- [ ] **Step 2: Clean "Gaps to Address" section**

Remove `/gsd` command references from the "Gaps to Address" list.

### Task 3: Final Verification

- [ ] **Step 1: Verify all files are in place**

Run: `ls docs/research/`

- [ ] **Step 2: Verify no `/gsd` references remain**

Run: `grep -r "/gsd" docs/research/`
