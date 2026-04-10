# Marketing Intelligence System — Architecture & README

> **Institutional marketing memory for high-scale content teams.**
> Built to be low-cost, low-maintenance, and compounding in value over time.

---

## Table of Contents

1. [What this system does](#what-this-system-does)
2. [Core design principles](#core-design-principles)
3. [System architecture](#system-architecture)
4. [Agent pipeline — detailed flow](#agent-pipeline--detailed-flow)
5. [Agent reference](#agent-reference)
6. [Tagging ontology](#tagging-ontology)
7. [Memory store design](#memory-store-design)
8. [Orchestration & loop control](#orchestration--loop-control)
9. [Economic context model](#economic-context-model)
10. [Cost & maintenance model](#cost--maintenance-model)
11. [Deployment guide](#deployment-guide)
12. [Pilot playbook — first 2 weeks](#pilot-playbook--first-2-weeks)
13. [What will break (and how to fix it)](#what-will-break-and-how-to-fix-it)

---

## What this system does

This is **not** a prompt wrapper or a "generate copy" tool.

It is a **self-improving marketing intelligence pipeline** that:

- Normalizes messy campaign briefs into structured data
- Reads institutional memory (past campaign performance) before generating strategy
- Produces channel-specific copy variants tagged with a controlled vocabulary
- Validates output against objectives, not just style guidelines
- Writes learnings back to memory after every run — so each campaign makes the next one smarter

After 10–15 campaigns per department, output quality begins to compound. After 50+, the system starts outperforming human intuition on hook selection and tone matching for known audience segments.

---

## Core design principles

| Principle | What it means in practice |
|---|---|
| **One agent, one decision type** | No agent mixes analysis + generation + validation. Failure isolation is clean. |
| **Never infer — warn or halt** | Missing critical fields halt the pipeline. Missing optional fields produce warnings and proceed. |
| **Controlled vocabulary, always** | No free-text tags anywhere. Dropdowns enforce the ontology invisibly at intake. |
| **LLM calls only where reasoning is needed** | Schema validation, memory writes, and routing logic run as functions — not LLM calls. |
| **Max 2 retry cycles, hard cap** | No infinite loops. Unresolved failures route to human review with the best available draft. |
| **Department isolation by default** | Memory namespaced per team. Cross-department reads require an explicit flag. |
| **Tag at source, not retrospectively** | A4 (Content Generator) tags each variation at creation time. Tags are never inferred from copy text later. |

---

## System architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INTAKE LAYER                                 │
│                                                                     │
│   Team submits brief via form (dropdowns enforce ontology)          │
│   ↓                                                                 │
│   [A1: Soft Normalizer]  →  structured JSON + warnings[]            │
│   (LLM call #1)              hard stop only on missing objective    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      INTELLIGENCE LAYER                             │
│                                                                     │
│   [A2: Memory Read + Data Intelligence]                             │
│   (LLM call #2)                                                     │
│   ├── reads memory store (filtered: channel + objective + recency)  │
│   ├── analyzes historical patterns                                  │
│   ├── detects fatigue signals                                       │
│   └── surfaces pattern conflicts with resolution_recommendation     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       STRATEGY LAYER                                │
│                                                                     │
│   [A3: Strategy Engine]                                             │
│   (LLM call #3)                                                     │
│   ├── conflict-aware (reads pattern_conflicts from A2)              │
│   ├── budget-aware (reads budget_tier + risk_profile from A1)       │
│   └── outputs strategy_confidence score                             │
│                                                                     │
│   [A3.5: Strategy Validator]  ← non-LLM check first, LLM on fail   │
│   ├── confirms strategy aligns with objective                       │
│   ├── confirms conflict_resolution is documented                    │
│   └── revise A3 once if invalid (then hard pass)                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      GENERATION LAYER                               │
│                                                                     │
│   [A4: Content Generator]                                           │
│   (LLM call #4)                                                     │
│   ├── variation count driven by budget_tier                         │
│   ├── each variation tagged at source (hook_type, tone, offer_type) │
│   ├── receives avoid_patterns[] explicitly from A2                  │
│   └── tags validated against controlled vocabulary (function)       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      VALIDATION LAYER                               │
│                                                                     │
│   [A5: Score-Banded Validator]                                      │
│   (LLM call #5)                                                     │
│                                                                     │
│   Score ≥ 70  ──────────────────────────────────► PROCEED          │
│   Score 50–69  ──► retry A4 once (copy issue)                       │
│   Score < 50   ──► escalate A3 (strategy issue)                     │
│   Score < 50 on 2nd attempt ──► HUMAN REVIEW FLAG                  │
│                                                                     │
│   Max 2 cycles. Hard cap. No exceptions.                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       OUTPUT LAYER                                  │
│                                                                     │
│   [A6: Experiment Planner]                                          │
│   (LLM call #6)                                                     │
│   └── A/B test plan scaled to budget_tier                           │
│                                                                     │
│   [Memory Write]  ← function call, NOT an LLM call                 │
│   └── writes: hook_type, tone, channel, score,                      │
│               conflict_resolution, campaign_id, dept                │
│                                                                     │
│   [Meta Agent Summary]                                              │
│   (LLM call #7 — optional, can be templated to save cost)          │
│   └── 30-second scan format for team leads                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent pipeline — detailed flow

```
User Input (form)
      │
      ▼
  ┌───────┐    objective      ┌──────────────┐
  │  A1   │──── missing? ────►│  HARD STOP   │
  │Normalizer   YES           │ return error │
  └───────┘                  └──────────────┘
      │ NO (pass even if partial)
      │ adds: budget_tier, risk_profile,
      │       input_confidence, warnings[]
      ▼
  ┌───────┐    no data +      ┌──────────────┐
  │  A2   │◄── memory empty?──│  SKIP A2     │
  │Memory │    YES            │ A3 uses      │
  │+ Data │                  │ general best │
  └───────┘                  │ practices    │
      │                      └──────────────┘
      │ outputs: top_patterns[], bad_patterns[],
      │          avoid_patterns[], pattern_conflicts[]
      ▼
  ┌───────┐
  │  A3   │
  │Strategy    outputs: messaging_angle, primary_hook,
  │Engine │    tone, conflict_resolution,
  └───────┘    strategy_confidence (0–100)
      │
      ▼
  ┌──────────┐   is_valid     ┌──────────────┐
  │  A3.5    │──── FALSE? ───►│ revise A3    │
  │Strategy  │               │ (once only)  │
  │Validator │               └──────┬───────┘
  └──────────┘                      │
      │ TRUE                        │ still fails → hard pass with warning
      ▼◄────────────────────────────┘
  ┌───────┐
  │  A4   │
  │Content    variation count = f(budget_tier)
  │Generator  each variation tagged at source
  └───────┘
      │
      ▼
  ┌───────┐
  │  A5   │
  │Validator
  └───┬───┘
      │
      ├──► score ≥ 70 ──────────────────────────────► A6
      │
      ├──► score 50–69 ──► retry A4 (copy fix)
      │         │
      │         └──► if same fail_reason → escalate immediately
      │
      └──► score < 50 ──► escalate A3 (strategy fix)
                │
                └──► if 2nd attempt < 50 ──► HUMAN REVIEW
                     output best draft + "needs_review" flag
      │
      ▼
  ┌───────┐
  │  A6   │  A/B plan scaled to budget_tier
  │Experiment
  │Planner│
  └───────┘
      │
      ▼
  ┌──────────────┐
  │ Memory Write │  ← function, not LLM
  │ (sync)       │  run does not close until confirmed
  └──────────────┘
      │
      ▼
  ┌──────────────┐
  │ Meta Summary │  ← LLM or template
  │ → team lead  │
  └──────────────┘
```

---

## Agent reference

### A1 — Soft Normalizer

**Type:** LLM call  
**Purpose:** Structure messy inputs. Flag gaps. Never block on non-critical fields.  
**Hard stop condition:** `objective` missing or completely ambiguous.

**Input:** Raw form submission  
**Output schema:**
```json
{
  "business_unit": "string",
  "campaign_type": "string",
  "target_audience": "string",
  "objective": {
    "primary_metric": "CTR | CVR | INSTALL | LTV",
    "priority": "scale | efficiency"
  },
  "channels": ["SMS", "WHATSAPP", "EMAIL", "SEARCH", "UAC", "PMAX"],
  "budget_tier": "test | scale | aggressive",
  "risk_profile": "conservative | balanced | high",
  "input_confidence": 85,
  "warnings": ["target_audience is broad — recommend age bracket"],
  "missing_optional": ["output_required"]
}
```

**System prompt snippet:**
```
You are a Context Normalization Agent.
Structure the input. Do NOT block execution except when objective is missing.
Assign input_confidence (0–100) based on completeness and specificity.
Document all assumptions in warnings[].
Budget tier rules: under ₹2L = test, ₹2L–₹20L = scale, above ₹20L = aggressive.
```

---

### A2 — Memory + Data Intelligence

**Type:** LLM call  
**Purpose:** Read from memory store, analyze patterns, detect conflicts. Provides the intelligence that makes output compound over time.  
**Skip condition:** No memory store data AND no uploaded historical data → proceed with warning.

**Input:** A1 output + memory store query results  
**Output schema:**
```json
{
  "retrieved_context": [],
  "top_patterns": [
    {"hook_type": "urgency", "channel": "SMS", "avg_ctr": 0.042, "sample_size": 18}
  ],
  "bad_patterns": [],
  "avoid_patterns": ["scarcity on EMAIL for NEW audience — 3 consecutive underperforms"],
  "fatigue_detected": true,
  "fatigue_details": {"hook_type": "reward", "segment": "repeat_users", "campaigns": 5},
  "pattern_conflicts": [
    {
      "conflict_type": "CTR_vs_CVR",
      "ctr_winner": "urgency",
      "cvr_winner": "trust",
      "resolution_recommendation": "objective is CTR — recommend urgency primary, trust as B variant"
    }
  ],
  "insight_confidence": 74
}
```

**Retrieval filter logic (function, not LLM):**
```python
def retrieve_patterns(dept, objective, channel, limit=20):
    return memory_store.query(
        namespace=dept,
        filters={
            "channel": channel,
            "objective_type": objective,
        },
        sort_by="recency_weight * performance_score",
        limit=limit
    )
```

---

### A3 — Strategy Engine

**Type:** LLM call  
**Purpose:** Decide what to say. Not how. Conflict-aware, budget-aware.

**Input:** A1 output + A2 output  
**Output schema:**
```json
{
  "messaging_angle": "Lead with time-limited cashback for high-intent repeat users",
  "primary_hook": "urgency",
  "tone": "functional",
  "offer_strategy": "cashback_flat",
  "conflict_resolution": "CTR_BIAS — urgency selected as primary, trust held for B variant",
  "risk_envelope": {
    "creativity_level": "medium",
    "experimentation_level": "high"
  },
  "strategy_confidence": 81,
  "risks": ["Urgency hook may fatigue segment if run >2 weeks"]
}
```

**System prompt snippet:**
```
You are a Marketing Strategy Engine.
Read pattern_conflicts[] from input and document your resolution in conflict_resolution.
Read budget_tier and risk_profile — conservative = proven hooks only,
high = full range including experimental.
Output strategy_confidence (0–100) honestly. Low confidence is useful data.
No copywriting. No generic advice.
```

---

### A3.5 — Strategy Validator

**Type:** Function check first, LLM only on failure  
**Purpose:** Gate before content generation. Prevents bad strategy from propagating through A4 and A5.  
**Cost note:** Run as JSON schema check first. Only invoke LLM if schema check fails.

**Input:** A3 output + A2 output  
**Output schema:**
```json
{
  "is_valid": true,
  "issues": [],
  "conflict_check": "confirmed | unresolved | overridden",
  "suggested_fix": ""
}
```

**Validation rules (function):**
```python
def validate_strategy(strategy, insights):
    issues = []
    # Rule 1: hook_type must be in controlled vocab
    if strategy["primary_hook"] not in HOOK_TYPES:
        issues.append("invalid hook_type")
    # Rule 2: conflict must be documented if conflicts exist
    if insights["pattern_conflicts"] and not strategy["conflict_resolution"]:
        issues.append("conflict_resolution missing")
    # Rule 3: conservative risk_profile must not use urgency/scarcity
    if strategy["risk_envelope"]["creativity_level"] == "low":
        if strategy["primary_hook"] in ["urgency", "scarcity"]:
            issues.append("aggressive hook on conservative risk profile")
    return {"is_valid": len(issues) == 0, "issues": issues}
```

---

### A4 — Content Generator

**Type:** LLM call  
**Purpose:** Generate copy variants. Tag each at source. Variation count driven by budget tier.

**Variation count by budget tier:**

| Tier | Variations | CTA aggression |
|---|---|---|
| test | 2 | soft |
| scale | 3–4 | moderate |
| aggressive | 5+ | direct |

**Input:** A3 output + avoid_patterns[] from A2  
**Output schema:**
```json
{
  "variations": [
    {
      "id": "v1",
      "hook_type": "urgency",
      "tone": "functional",
      "offer_type": "cashback_flat",
      "headline": "Pay now. Get ₹50 back. Offer ends at midnight.",
      "description": "Use Paytm UPI for any payment above ₹200 today.",
      "cta": "Pay & Earn",
      "cta_type": "urgency_driven",
      "char_counts": {"headline": 42, "description": 51, "cta": 8}
    }
  ],
  "variation_count": 3
}
```

**System prompt snippet:**
```
You are a Performance Copywriting Agent.
Generate exactly {variation_count} variations.
Each variation must have a distinct hook_type from the controlled vocabulary.
Tag each variation at source — do not leave tags blank.
Avoid all patterns in avoid_patterns[].
Follow character limits strictly: headline ≤ 60, description ≤ 90, CTA ≤ 20.
```

---

### A5 — Score-Banded Validator

**Type:** LLM call  
**Purpose:** Score content. Route based on score band. Never rewrite.

**Scoring bands:**

| Score | Status | Action |
|---|---|---|
| ≥ 70 | PASS | proceed to A6 |
| 50–69 | SOFT_RETRY | retry A4 once (copy issue) |
| < 50 | ESCALATE | escalate to A3 (strategy issue) |
| < 50 on 2nd | HUMAN_REVIEW | flag + output best draft |

**Output schema:**
```json
{
  "score": 73,
  "status": "PASS",
  "issues": {
    "critical": [],
    "moderate": ["description slightly generic on v2"],
    "minor": ["CTA could be sharper"]
  },
  "fail_reason": null,
  "retry_count": 0
}
```

---

### A6 — Experiment Planner

**Type:** LLM call  
**Purpose:** Design A/B plan. Then trigger memory write (function).

**Output schema:**
```json
{
  "test_plan": "2-arm test: v1 (urgency) vs v3 (trust) on SMS, 50/50 split, 7 days",
  "variables": ["hook_type"],
  "success_metric": "CTR at 72h",
  "expected_learning": "Which hook wins for repeat users on SMS for wallet cashback",
  "memory_write": {
    "dept": "wallet",
    "hook_type": "urgency",
    "tone": "functional",
    "offer_type": "cashback_flat",
    "channel": "SMS",
    "audience_type": "REPEAT",
    "funnel_stage": "RETENTION",
    "objective_type": "CTR",
    "conflict_resolution": "CTR_BIAS",
    "validator_score": 73,
    "campaign_id": "WAL-2024-114",
    "decay_weight": 1.0
  },
  "memory_written": false
}
```

**Memory write is a function call, not LLM:**
```python
def write_memory(payload):
    payload["created_at"] = datetime.utcnow()
    payload["decay_weight"] = 1.0  # decays on each subsequent read cycle
    memory_store.insert(
        namespace=payload["dept"],
        data=payload
    )
    return {"memory_written": True}
```

---

## Tagging ontology

This is the system's brain. All other capabilities — memory retrieval, conflict detection, fatigue signals, compounding learning — depend on tags being consistent. **This schema is a hard constraint, not a guideline.**

### Core schema

```json
{
  "hook_type": "URGENCY | SCARCITY | TRUST | CONVENIENCE | REWARD | IDENTITY | OTHER",
  "hook_subtype": "string (≤ 30 chars, required if hook_type = OTHER)",

  "tone": "FUNCTIONAL | WARM | URGENT | ASPIRATIONAL | REASSURING | PLAYFUL",

  "offer_type": "CASHBACK_FLAT | CASHBACK_PCT | LOYALTY_REWARD | REFERRAL | TRIAL_FREE | NO_OFFER",

  "cta_type": "DIRECT | SOFT | URGENCY_DRIVEN | BENEFIT_LED",

  "audience_type": "NEW | REPEAT | HIGH_INTENT | LOW_INTENT",

  "funnel_stage": "ACQUISITION | ACTIVATION | RETENTION",

  "channel": "SMS | WHATSAPP | EMAIL | SEARCH | UAC | PMAX | DEMAND_GEN | IN_APP",

  "objective_type": "CTR | CVR | INSTALL | LTV",

  "creative_format": "TEXT | IMAGE | VIDEO | CAROUSEL",

  "conflict_resolution": "CTR_BIAS | CVR_BIAS | BALANCED | NOT_APPLICABLE"
}
```

### Enforcement rules

1. **No free-text input on primary fields.** UI uses dropdowns. API validates against enum before passing to any agent.
2. **`hook_type: OTHER` requires `hook_subtype`** — max 30 characters, enforced by schema validator.
3. **Tags are set at A4 (generation time).** They are never inferred retrospectively from copy text.
4. **Schema validator runs as a function after A4.** Invalid tags return a soft error to A4 for correction before the pipeline continues. This is never skipped.
5. **`hook_subtype` values that appear 3+ times are candidates for promotion to a named hook_type** — reviewed quarterly by the content team.

### Hook type definitions

| Hook type | Mechanism | Use when |
|---|---|---|
| `URGENCY` | Time-limited pressure | Real deadline exists. "Offer ends tonight." |
| `SCARCITY` | Quantity-limited pressure | Slot or inventory is genuinely limited |
| `TRUST` | Social proof, authority | Acquisition, skeptical segments |
| `CONVENIENCE` | Friction removal | Feature adoption, how-to campaigns |
| `REWARD` | Direct incentive | Offer is strong enough to lead with |
| `IDENTITY` | Aspiration, belonging | Brand campaigns, reactivation |
| `OTHER` | Emerging formats | Meme-led, trend hijack — requires subtype |

---

## Memory store design

### Storage recommendation

**Use a vector database for pattern retrieval + a relational table for metadata.**

For low cost and low maintenance:

| Component | Recommended option | Cost |
|---|---|---|
| Vector store | Supabase pgvector (Postgres extension) | ~$25/mo for most teams |
| Metadata store | Same Supabase instance | Included |
| Embeddings | `text-embedding-3-small` (OpenAI) | ~$0.02 per 1M tokens |
| Hosting | Supabase free tier to start | $0 until scale |

**Why not Pinecone, Weaviate, etc.:** More infrastructure to maintain. Supabase gives you vector search + relational queries in one place, which is what retrieval filtering requires.

### Schema

```sql
CREATE TABLE campaign_memory (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dept            TEXT NOT NULL,           -- strict namespace
  campaign_id     TEXT NOT NULL,
  hook_type       TEXT NOT NULL,           -- controlled vocab
  hook_subtype    TEXT,
  tone            TEXT NOT NULL,
  offer_type      TEXT NOT NULL,
  cta_type        TEXT,
  channel         TEXT NOT NULL,
  audience_type   TEXT NOT NULL,
  funnel_stage    TEXT NOT NULL,
  objective_type  TEXT NOT NULL,
  conflict_resolution TEXT,
  validator_score INTEGER NOT NULL,
  performance_outcome JSONB,               -- populated after campaign
  decay_weight    FLOAT DEFAULT 1.0,       -- decremented on each read cycle
  embedding       VECTOR(1536),            -- for semantic retrieval
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Index for fast dept-scoped retrieval
CREATE INDEX idx_dept_channel ON campaign_memory(dept, channel);
CREATE INDEX idx_dept_objective ON campaign_memory(dept, objective_type);
```

### Retrieval query

```sql
-- A2's memory read: filtered + recency + performance weighted
SELECT *,
  (decay_weight * 0.4 + 
   COALESCE((performance_outcome->>'ctr')::float, 0) * 0.4 +
   (1.0 / (EXTRACT(EPOCH FROM (now() - created_at)) / 86400 + 1)) * 0.2
  ) AS relevance_score
FROM campaign_memory
WHERE dept = $1
  AND channel = $2
  AND objective_type = $3
ORDER BY relevance_score DESC
LIMIT 20;
```

### Decay logic

Older entries lose influence gradually. The `decay_weight` field starts at 1.0 and is decremented by 0.05 on each read cycle where the campaign is surfaced but not selected as a top pattern. This prevents the system from over-indexing on early campaigns that happened to perform well in a different market context.

---

## Orchestration & loop control

### Orchestration logic (pseudocode)

```python
def run_pipeline(brief):
    # A1 — always runs
    context = normalize(brief)
    if context["objective"] is None:
        return error("OBJECTIVE_REQUIRED")

    # A2 — skip if no data available
    if context["data_available"] or memory_has_data(context["dept"]):
        intelligence = analyze(context)
    else:
        intelligence = {"top_patterns": [], "pattern_conflicts": [], "insight_confidence": 0}
        intelligence["warnings"] = ["No memory data — strategy uses general best practices"]

    # A3 + A3.5
    strategy = generate_strategy(context, intelligence)
    validation = validate_strategy(strategy, intelligence)  # function first
    if not validation["is_valid"]:
        strategy = generate_strategy(context, intelligence, escalation_reason=validation["issues"])
        # A3 gets one revision. After that, hard pass.

    # A4
    content = generate_content(strategy, intelligence)
    tag_errors = validate_tags(content)  # function, not LLM
    if tag_errors:
        content = generate_content(strategy, intelligence, tag_correction=tag_errors)

    # A5 — with retry loop
    retry_count = 0
    last_fail_reason = None
    while retry_count < 2:
        score = validate_content(content)
        if score["score"] >= 70:
            break
        if score["fail_reason"] == last_fail_reason:
            # same reason twice = escalate immediately
            strategy = generate_strategy(context, intelligence, 
                                         escalation_reason=score["fail_reason"])
            content = generate_content(strategy, intelligence)
        elif score["score"] >= 50:
            content = generate_content(strategy, intelligence)  # soft retry
        else:
            strategy = generate_strategy(context, intelligence,
                                         escalation_reason=score["fail_reason"])
            content = generate_content(strategy, intelligence)
        last_fail_reason = score["fail_reason"]
        retry_count += 1

    if score["score"] < 50:
        content["status"] = "HUMAN_REVIEW"

    # A6 + memory write
    plan = plan_experiment(content, context)
    write_memory(plan["memory_write"])  # sync, confirmed before close

    return summarize(context, strategy, content, plan, score)
```

### Loop control rules

| Rule | Detail |
|---|---|
| Max 2 retry cycles | Hard cap. No exceptions. |
| Same fail_reason twice | Immediate escalation. Don't wait for the full cycle. |
| A1 never loops | Runs once. Missing required fields → return error to user. |
| A3.5 revision limit | A3 gets one strategy revision. If still invalid, hard pass with warning. |
| Memory write is sync | Pipeline does not close until write confirms. |
| Memory read is async | 2-second timeout. Failure → proceed with warning, not halt. |

---

## Economic context model

Three variables together define the **creative risk envelope**. All three are captured at A1.

```
Creative risk envelope = f(budget_size, campaign_maturity, kpi_pressure)
```

| Variable | Values | Effect |
|---|---|---|
| `budget_tier` | test / scale / aggressive | Controls variation count and testing structure |
| `campaign_maturity` | new / scaling / saturated | Controls exploration vs exploitation ratio |
| `kpi_pressure` | relaxed / balanced / aggressive | Controls CTA aggression and hook risk |

### Risk envelope → behavior mapping

| budget_tier | campaign_maturity | kpi_pressure | Behavior |
|---|---|---|---|
| test | new | relaxed | Proven hooks only. 2 variations. Soft CTAs. |
| test | new | aggressive | Proven hooks only, but direct CTAs. Push harder on copy. |
| scale | scaling | balanced | 3–4 variations. One new hook type allowed alongside proven. |
| aggressive | scaling | aggressive | Full hook range. 5+ variations. Contrasting angles required. |
| aggressive | saturated | aggressive | Force new hook types. Fatigue signals override pattern preference. |

### Character limits by channel

| Channel | Headline | Description | CTA |
|---|---|---|---|
| SMS | 160 chars total | — | — |
| WhatsApp | 60 | 1024 | 20 |
| Email subject | 50 | — | — |
| Search (RSA) | 30 × 15 | 90 × 4 | — |
| In-app banner | 40 | 80 | 20 |
| Push notification | 50 | 100 | 15 |

---

## Cost & maintenance model

### LLM call budget per campaign run

| Step | Type | Est. tokens (in+out) | Est. cost (Sonnet) |
|---|---|---|---|
| A1 Normalizer | LLM | ~800 | ~$0.004 |
| A2 Data Intelligence | LLM | ~2,000 | ~$0.010 |
| A3 Strategy | LLM | ~1,500 | ~$0.008 |
| A3.5 Validator | Function first, LLM on fail | ~500 (if needed) | ~$0.003 |
| A4 Content Generator | LLM | ~2,500 | ~$0.013 |
| A5 Validator | LLM | ~1,500 | ~$0.008 |
| A6 Experiment Planner | LLM | ~1,000 | ~$0.005 |
| Meta Summary | Template (no LLM) | — | $0 |
| Memory Write | Function | — | $0 |
| **Total (happy path)** | | **~9,800 tokens** | **~$0.05** |
| **Total (1 retry cycle)** | | **~13,000 tokens** | **~$0.07** |

> **At 100 campaigns/month: ~$5–7/month in LLM costs.**
> Infrastructure (Supabase): ~$25/month.
> **Total system cost: ~$30–35/month** at moderate usage.

### What is NOT an LLM call (cost-free steps)

- A1 → A2 schema validation
- A4 tag validation against controlled vocabulary
- Orchestration routing logic
- Memory write
- Memory retrieval query (SQL)
- Meta summary (if templated)

### Maintenance surface

| Component | Maintenance required | Frequency |
|---|---|---|
| Agent prompts | Tune if output quality drifts | Quarterly |
| Tagging ontology | Add new hook subtypes; promote to named types | Quarterly |
| Memory decay weights | Adjust if old campaigns over-influence | Semi-annually |
| Channel character limits | Update when platforms change specs | As needed |
| Supabase schema | Migrations if new fields needed | Rarely |

---

## Deployment guide

### Prerequisites

- Node.js 18+ or Python 3.11+
- Supabase account (free tier sufficient to start)
- Anthropic API key (Claude Sonnet recommended)
- Existing campaign data as CSV (optional but valuable)

### Step 1 — Set up memory store

```bash
# Install Supabase CLI
npm install -g supabase

# Initialize and run migrations
supabase init
supabase db push  # applies schema from /db/migrations/
```

### Step 2 — Configure environment

```env
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
DEFAULT_MODEL=claude-sonnet-4-20250514
MAX_RETRIES=2
MEMORY_READ_TIMEOUT_MS=2000
```

### Step 3 — Load historical data (if available)

```bash
# Import past campaign data into memory store
python scripts/import_campaigns.py \
  --input past_campaigns.csv \
  --dept wallet \
  --dry-run  # check mapping before committing
```

The import script maps your existing columns to the ontology schema and flags any values that don't match the controlled vocabulary.

### Step 4 — Run first campaign

```bash
python run_pipeline.py \
  --brief briefs/sample_brief.json \
  --dept wallet \
  --dry-run  # outputs without writing to memory
```

### Step 5 — Connect intake form

See `/ui/intake-form/` for the HTML form with dropdown enforcement. Deploy to any static host (Vercel, Netlify, Cloudflare Pages — all free tier sufficient).

---

## Pilot playbook — first 2 weeks

### Week 1 — One team, controlled conditions

- Pick one department (recommend: whichever has the most historical campaign data)
- Run 5 campaigns through the system in parallel with the existing process
- Do not replace the existing process yet — run side by side
- Compare outputs. Note where the system is weaker (usually: nuance, brand voice edge cases)
- Fix prompt issues found. Do not fix ontology yet.

### Week 2 — Trust-building

- Run 10 campaigns. Team uses system output as first draft, edits freely
- **Critical:** Enable edit tracking. Every human edit captures a `why_changed` reason (dropdown: tone / offer / hook / compliance / other)
- These edit reasons are the most valuable training signal in the system
- After week 2: check which `why_changed` reasons appear most. These point to either prompt gaps or ontology gaps.

### Success criteria at 2 weeks

| Metric | Target |
|---|---|
| System adoption rate | ≥ 70% of campaigns run through pipeline |
| First-pass validator score | ≥ 65 average |
| Human edit rate on output | < 40% of variations edited |
| `why_changed` reason captured | 100% of edits |

---

## What will break (and how to fix it)

### 1. Inconsistent tagging in week 1

**Symptom:** Team manually edits tags after A4. `hook_type` drifts to free text.  
**Fix:** Hard-block free text at the UI layer. This is the one rule that cannot be softened. If the intake form has a text field where dropdowns should be, teams will use it.

### 2. A2 retrieves irrelevant patterns

**Symptom:** Strategy feels mismatched to the brief. A3 confidence scores are low.  
**Fix:** Check retrieval filters. Usually the channel or audience_type filter is missing or too broad. Tighten the SQL query's WHERE clause.

### 3. A5 scores too harshly or too loosely

**Symptom:** Too many SOFT_RETRY routes (score 50–69) on copy that's actually fine.  
**Fix:** Calibrate the A5 system prompt. Add 3–5 example scored outputs as few-shot examples. This is the highest-leverage prompt tuning you can do.

### 4. Memory write succeeds but retrieval returns nothing

**Symptom:** A2 consistently skips memory even after 20+ campaigns.  
**Fix:** Check that `dept` namespacing in the write matches the `dept` in the retrieval query exactly. Case sensitivity issue is the most common cause.

### 5. Teams bypass A1 and go straight to A3

**Symptom:** Campaigns in memory store have missing `audience_type` or `funnel_stage`.  
**Fix:** A1 is mandatory. Enforce at the orchestration layer — not at the UI layer. The pipeline function should reject any input that hasn't been through A1's schema normalization.

---

*Last updated: V3 architecture — post stress-test review*  
*Status: Ready for pilot*
