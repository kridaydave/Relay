# Design: Relay Marketing Campaign (Wave 1)

**Topic:** Introducing Relay to the developer community
**Persona:** The Frustrated Creator ("AIs talking out their ass")
**Narrative:** Surgical Tool vs. Framework Bloat

---

## 1. Reddit Strategy (r/Python, r/MachineLearning, r/LocalLLM)

**Post Style:** Long-form, story-driven, technical but accessible.

**Draft Content:**
> **Title:** I got tired of my AI agents hallucinating Blinkit orders and leaking my API keys, so I built Relay.
>
> **The Hook:**
> We’ve all been there. You build a cool 3-step agent pipeline, and by step 3, Agent C is convinced I want to order bananas on Blinkit because of some hallucinated context from Agent A. Or worse, Agent B decides to "helpfully" include a raw environment variable in its output to Agent C.
>
> Most frameworks treat context as a mutable string blob. I think that's why our pipelines are so brittle.
>
> **The Solution (Relay):**
> I built a thin, zero-dependency middleware that treats agent context like a **ledger**, not a string. 
>
> - **Immutable Snapshots:** Every handoff is saved. If an agent hallucinates, you don't "fix" it; you just roll back to the last clean checkpoint.
> - **HMAC Signatures:** If anything tampers with the context between steps, validation fails.
> - **Manifests:** You define what an agent can READ and WRITE. If it tries to write to a section it shouldn't (like where your keys are), Relay blocks it.
> - **Hard Token Budgets:** No more surprise $500 bills because a loop went rogue.
>
> **Why I'm posting:**
> I've been grinding on this (75 commits today alone) and it's at v0.4. It’s pure Python, stdlib only, no bloat. I need builders to break it and tell me where the "agent-to-agent" pain points still exist.
>
> **Links:** 
> - GitHub: [kridaydave/Relay]
> - Docs: [kridaydave.github.io/Relay]

---

## 2. Twitter (X) Strategy

**Post Style:** Punchy thread, "Technical Alpha" vibe.

**Thread Breakdown:**
1. **Hook:** Why are we still passing AI context as mutable strings? I got tired of my agents "hallucinating" grocery orders and leaking credentials, so I built Relay. ⚡
2. **The Core Idea:** Relay is the connective tissue for multi-agent systems. It doesn't replace LangChain/CrewAI—it makes them reliable.
3. **The Tech:** 
   - 🔒 HMAC-signed envelopes
   - 📸 Deterministic rollbacks
   - 🛡️ Manifest-based permissions
   - 💸 Hard token caps
4. **The Vibe:** Pure Python. Stdlib only. Zero dependencies. It's a surgical tool, not a magic box. 
5. **CTA:** Just hit v0.4. Check the ledger-style architecture here: [Link] #AI #Python #LLM

---

## 3. Discord Strategy (Framework communities: CrewAI, LangChain, etc.)

**Post Style:** Helpful utility, "I made this for us."

**Draft Content:**
> Hey everyone! I’ve been building a lot with [Framework Name] and kept hitting the same wall: context corruption. One agent hallucinates, and the whole pipeline is toast.
>
> I made a middleware called **Relay** that adds a safety layer to agent handoffs. It adds HMAC signatures and automated rollbacks so you don't have to worry about data leaking or agents "talking out their ass" midway through a run. 
> 
> It's framework-agnostic (bundled adapters for LangChain/CrewAI/AutoGen). Would love for some of you guys to try it out in your more "unstable" pipelines.
