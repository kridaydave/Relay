# Documentation Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate all GSD artifacts into standard project documentation, remove jargon, and clean up the workspace.

**Architecture:** Merge technical details into core docs, relocate PM files to root, and organize research/audits into subdirectories.

**Tech Stack:** Markdown

---

### Task 1: Expand Relay Design Document

**Files:**
- Modify: `docs/Relay Design Document.md`
- Source: `docs/STRUCTURE.md`, `docs/INTEGRATIONS.md`, `docs/ARCHITECTURE.md`

- [ ] **Step 1: Append Component Structure**
Read `docs/STRUCTURE.md` and append a cleaned-up version to `docs/Relay Design Document.md`.
- [ ] **Step 2: Append External Integrations**
Read `docs/INTEGRATIONS.md` and append to `docs/Relay Design Document.md`.
- [ ] **Step 3: Append Data Flow Details**
Read `docs/ARCHITECTURE.md` (the codebase version) and integrate key state transition details into `docs/Relay Design Document.md`.

---

### Task 2: Expand Relay Engineering Standards (Coding Rules)

**Files:**
- Modify: `docs/Relay Coding Rules.md`
- Source: `docs/TESTING.md`, `docs/STACK.md`, `docs/CONCERNS.md`

- [ ] **Step 1: Append Testing Standards**
Integrate requirements from `docs/TESTING.md` into `docs/Relay Coding Rules.md`.
- [ ] **Step 2: Append Tech Stack Justification**
Append content from `docs/STACK.md` to `docs/Relay Coding Rules.md`.
- [ ] **Step 3: Append Constraints & Concerns**
Append "Known Constraints" from `docs/CONCERNS.md` to `docs/Relay Coding Rules.md`.

---

### Task 3: Relocate Project Management Files

**Files:**
- Move: `docs/ROADMAP.md` -> `docs/ROADMAP.md`
- Move: `docs/REQUIREMENTS.md` -> `docs/REQUIREMENTS.md`

- [ ] **Step 1: Move and Clean Roadmap**
Move file and remove any `/gsd-` command references.
- [ ] **Step 2: Move and Clean Requirements**
Move file and ensure it reads as a standard project requirements doc.

---

### Task 4: Organize Audits

**Files:**
- Create Dir: `docs/audits/`
- Move: `docs/audits/INTEGRATION.md` -> `docs/audits/2026-05-17-integration-audit.md`
- Move: `docs/audits/REVIEW.md` -> `docs/audits/2026-05-17-code-review.md`
- Move: `docs/audits/SECURITY.md` -> `docs/audits/2026-05-17-security-audit.md`
- Move: `docs/audits/REVIEW-FIX.md` -> `docs/audits/2026-05-17-review-fix-log.md`

- [ ] **Step 1: Move and strip GSD headers**
Move each file and remove the YAML-like headers (phase, reviewed, Fixer, etc.).

---

### Task 5: Organize Research

**Files:**
- Create Dir: `docs/research/`
- Move: `docs/research/ARCHITECTURE.md` -> `docs/research/architecture-deep-dive.md`
- Move: `docs/research/PITFALLS.md` -> `docs/research/implementation-pitfalls.md`
- Move: `docs/research/FEATURES.md` -> `docs/research/feature-explainer.md`
- Move: `docs/research/SUMMARY.md` -> `docs/research/research-summary.md`

- [ ] **Step 1: Move and Clean Research**
Move files and remove GSD-specific "Recommendations" sections that refer to `/gsd` commands.

---

### Task 6: Final Cleanup and Link Update

**Files:**
- Delete: `.planning/`
- Delete: `docs/audits/`
- Modify: `README.md`, `docs/Relay Design Document.md`, `docs/Relay Coding Rules.md`

- [ ] **Step 1: Update Internal Links**
Search for links to `.planning/` or `docs/audits/` in the new `docs/` structure and update them.
- [ ] **Step 2: Delete GSD directories**
Remove the now-redundant folders.
- [ ] **Step 3: Update README**
Ensure README documentation section points to the new `docs/` structure.
