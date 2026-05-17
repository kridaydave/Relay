# Relay Website — Design Spec
**Date:** 2026-05-17
**Status:** Approved

## Goal

Single landing page for the Relay open-source Python library. Primary outcome: developer finds Relay via search/social, understands what it does in 30 seconds, installs it.

## Hosting & Deployment

- **Host:** GitHub Pages
- **Source:** `docs/website/` folder, `main` branch
- **Deploy:** Push to main → live. No CI, no build step.
- **GitHub Pages config:** Set source to `docs/website/` in repo settings.

## Tech Stack

- Plain HTML/CSS/JS — zero build step, zero dependencies
- Prism.js — bundled locally (no CDN), syntax highlighting for Python code blocks
- No external fonts, no analytics, no tracking

## File Structure

```
docs/website/
├── index.html
├── style.css
├── main.js        (copy button, tab switching, smooth scroll)
└── prism.js       (bundled Prism, Python language pack)
```

## Page Sections (top to bottom)

### 1. Nav
- Sticky, `backdrop-filter: blur(8px)` on scroll
- Left: logo (48px) + "Relay" wordmark
- Right: [GitHub] [PyPI] links

### 2. Hero
- Logo image centered (~120px)
- H1: "Agent-agent context passing, done right."
- Subline: "Lightweight Python middleware that signs, validates, and rolls back AI agent context automatically."
- Install block: `pip install relay-middleware` + clipboard copy button
- CTAs: [View on GitHub] [PyPI v0.4.2]

### 3. Problem / Solution
- Two-column layout (stacks on mobile)
- Left: "The Problem" — one hallucinating agent silently corrupts shared context; every downstream agent inherits the damage
- Right: "The Solution" — Relay treats context like a ledger: append-only, signed at every step, reversible

### 4. Features
- 3-column card grid (stacks to 1-col on mobile)
- 6 cards:
  1. Cryptographic Signing — every envelope signed + verified
  2. Automatic Rollback — contradiction detected → last clean checkpoint restored
  3. Parallel Fork-Join — UNION / VOTE / FIRST_WINS strategies
  4. Budget Enforcement — hard token cap before every agent call
  5. Any LLM / Framework — LangChain, OpenAI, Anthropic, Ollama, CrewAI, AutoGen
  6. Type Safe — PEP 561, mypy --strict, zero type: ignore

### 5. Code Examples
- Tabbed toggle: "Without Relay" / "With Relay"
- Prism.js Python syntax highlighting
- Source: verbatim from README "Aha Moment" section

### 6. Footer
- "MIT License · Built by Kriday and team"
- Links: GitHub, PyPI

## Visual Design

| Token | Value |
|---|---|
| Background | `#0a0a0a` |
| Surface | `#111111` |
| Border | `#1f1f1f` |
| Text primary | `#f0f0f0` |
| Text muted | `#888888` |
| Accent | `#e8490f` |
| Accent hover | `#ff6a2f` |
| Code bg | `#111111` |
| Font | system-ui, -apple-system, sans-serif |

- Logo: `docs/Images/Retro_relay_station_icon_202605151828.jpeg`
- No drop shadows — subtle borders only
- Feature cards: `#111` bg, `#1f1f1f` border, accent-colored icon/emoji

## Responsiveness

- Mobile-first CSS
- Nav collapses to logo + hamburger at < 640px (or just stacks links)
- Feature grid: 3-col → 1-col
- Problem/Solution: 2-col → 1-col
- Code blocks: horizontally scrollable on small screens

## Out of Scope

- Docs site / API reference (GitHub README serves this)
- Blog
- Analytics / tracking
- Contact form
