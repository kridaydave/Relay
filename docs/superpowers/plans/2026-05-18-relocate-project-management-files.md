# Relocate Project Management Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate planning artifacts into standard documentation by moving ROADMAP.md and REQUIREMENTS.md to the docs/ directory and removing GSD-specific command references.

**Architecture:** File relocation and content cleaning.

**Tech Stack:** Markdown

---

### Task 1: Relocate and Clean ROADMAP.md

**Files:**
- Create: `docs/ROADMAP.md`
- Original: `docs/ROADMAP.md`

- [ ] **Step 1: Read original ROADMAP.md**
- [ ] **Step 2: Create docs/ROADMAP.md without GSD commands**

Write the content of `docs/ROADMAP.md` to `docs/ROADMAP.md`, but stop before the `/gsd-` command references at the bottom.

- [ ] **Step 3: Verify content of docs/ROADMAP.md**
Check that the file ends with `---` and `*Created: 2026-05-17*` (or similar date metadata) but NO `/gsd-` commands.

### Task 2: Relocate and Clean REQUIREMENTS.md

**Files:**
- Create: `docs/REQUIREMENTS.md`
- Original: `docs/REQUIREMENTS.md`

- [ ] **Step 1: Read original REQUIREMENTS.md**
- [ ] **Step 2: Create docs/REQUIREMENTS.md**

Write the content of `docs/REQUIREMENTS.md` to `docs/REQUIREMENTS.md`. This file didn't have `/gsd-` commands but ensure it's clean and consistent with project documentation.

- [ ] **Step 3: Verify content of docs/REQUIREMENTS.md**

### Task 3: Cleanup (Optional/Verification)

**Files:**
- Original: `docs/ROADMAP.md`
- Original: `docs/REQUIREMENTS.md`

- [ ] **Step 1: Verify the new files exist in docs/**
- [ ] **Step 2: Acknowledge that old files will be deleted by the controller later**
(As per instructions: "you can just move them and I'll confirm. ... I (the controller) will handle the final deletion of the old files in a later task.")
Wait, the instruction also says "Move file", which usually means delete source. But then says "I (the controller) will handle the final deletion of the old files in a later task."
Actually, if I "move" them using `mv` or similar, they are deleted. If I `write_file` to new location, they remain.
I will follow the instruction "you can just move them and I'll confirm" which implies deletion of source is fine, but the contradictory "I (the controller) will handle the final deletion" makes me lean towards just creating the new ones and letting the controller delete.
However, "Relocate" usually means Move.
I'll use `write_file` to the new locations first.
Actually, I'll just use `run_shell_command` to `mv` them if I was sure, but I need to clean them.
So I will `read`, then `write` to new location, then I'll leave the originals as per "controller will handle final deletion".

Wait, I'll re-read: "you can just move them and I'll confirm. Actually, you can just move them and I'll confirm. Actually, you can just move them and I'll confirm. Actually, you can just move them and I'll confirm. Actually, you can just move them and I'll confirm. ... I (the controller) will handle the final deletion of the old files in a later task."

Okay, I'll create the new ones and NOT delete the old ones.

- [ ] **Step 1: Verify docs/ROADMAP.md exists and is clean**
- [ ] **Step 2: Verify docs/REQUIREMENTS.md exists and is clean**
