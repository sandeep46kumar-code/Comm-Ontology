"""
Marketing Intelligence System — Pipeline Orchestrator
V3 Architecture

Runs the full agent pipeline with:
- Soft input handling (A1)
- Memory-augmented intelligence (A2)
- Strategy + validation gate (A3, A3.5)
- Content generation with tag enforcement (A4)
- Score-banded validation with smart retry (A5)
- Experiment planning + memory write (A6)

LLM: Claude Sonnet (Anthropic)
Memory: Supabase (pgvector)
Non-LLM steps: Python functions (free to run)
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional
import anthropic
from supabase import create_client

# ── Config ────────────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048
MAX_RETRY_CYCLES = 2
MEMORY_READ_TIMEOUT = 2.0  # seconds

# ── Controlled vocabulary (mirrors ontology/tag-schema.json) ─────────────────

HOOK_TYPES     = {"URGENCY","SCARCITY","TRUST","CONVENIENCE","REWARD","IDENTITY","OTHER"}
TONES          = {"FUNCTIONAL","WARM","URGENT","ASPIRATIONAL","REASSURING","PLAYFUL"}
OFFER_TYPES    = {"CASHBACK_FLAT","CASHBACK_PCT","LOYALTY_REWARD","REFERRAL","TRIAL_FREE","NO_OFFER"}
CTA_TYPES      = {"DIRECT","SOFT","URGENCY_DRIVEN","BENEFIT_LED"}
AUDIENCE_TYPES = {"NEW","REPEAT","HIGH_INTENT","LOW_INTENT"}
FUNNEL_STAGES  = {"ACQUISITION","ACTIVATION","RETENTION"}
CHANNELS       = {"SMS","WHATSAPP","EMAIL","SEARCH","UAC","PMAX","DEMAND_GEN","IN_APP","PUSH"}
OBJECTIVE_TYPES= {"CTR","CVR","INSTALL","LTV"}

# ── Helper: call Claude ────────────────────────────────────────────────────────

def llm(system_prompt: str, user_content: str) -> dict:
    """Single LLM call. Returns parsed JSON."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt + "\n\nRespond ONLY with valid JSON. No preamble, no markdown fences.",
        messages=[{"role": "user", "content": user_content}]
    )
    return json.loads(response.content[0].text)

# ── Non-LLM functions (free to run) ───────────────────────────────────────────

def validate_tags(content: dict) -> list[str]:
    """
    Validates A4 output tags against controlled vocabulary.
    Returns list of errors. Empty list = valid.
    This is a function call — NOT an LLM call.
    """
    errors = []
    for variation in content.get("variations", []):
        if variation.get("hook_type") not in HOOK_TYPES:
            errors.append(f"Invalid hook_type: {variation.get('hook_type')}")
        if variation.get("hook_type") == "OTHER" and not variation.get("hook_subtype"):
            errors.append("hook_type=OTHER requires hook_subtype")
        if variation.get("hook_subtype") and len(variation["hook_subtype"]) > 30:
            errors.append("hook_subtype exceeds 30 characters")
        if variation.get("tone") not in TONES:
            errors.append(f"Invalid tone: {variation.get('tone')}")
        if variation.get("offer_type") not in OFFER_TYPES:
            errors.append(f"Invalid offer_type: {variation.get('offer_type')}")
    return errors


def validate_strategy_schema(strategy: dict, intelligence: dict) -> dict:
    """
    Schema-level strategy validation.
    Runs as a function first. LLM only invoked if this fails.
    """
    issues = []

    if strategy.get("primary_hook") not in HOOK_TYPES:
        issues.append(f"Invalid primary_hook: {strategy.get('primary_hook')}")

    if strategy.get("tone") not in TONES:
        issues.append(f"Invalid tone: {strategy.get('tone')}")

    conflicts = intelligence.get("pattern_conflicts", [])
    if conflicts and not strategy.get("conflict_resolution"):
        issues.append("conflict_resolution missing despite pattern conflicts in intelligence")

    risk = strategy.get("risk_envelope", {})
    if risk.get("creativity_level") == "LOW":
        if strategy.get("primary_hook") in {"URGENCY", "SCARCITY"}:
            issues.append("Aggressive hook on conservative risk profile — mismatch")

    return {
        "is_valid": len(issues) == 0,
        "issues": issues,
        "conflict_check": "confirmed" if not conflicts or strategy.get("conflict_resolution") else "unresolved",
        "suggested_fix": "; ".join(issues) if issues else ""
    }


def write_memory(payload: dict) -> bool:
    """
    Writes campaign data to Supabase memory store.
    Synchronous — pipeline does not close until confirmed.
    This is a function call — NOT an LLM call.
    """
    try:
        payload["created_at"] = datetime.utcnow().isoformat()
        payload["decay_weight"] = 1.0
        result = supabase.table("campaign_memory").insert(payload).execute()
        return True
    except Exception as e:
        print(f"Memory write failed: {e}")
        return False


def read_memory(dept: str, channel: str, objective: str) -> list[dict]:
    """
    Reads filtered + weighted patterns from memory store.
    Async with timeout — if slow, pipeline proceeds without memory.
    This is a SQL query — NOT an LLM call.
    """
    try:
        result = supabase.rpc("get_weighted_patterns", {
            "p_dept": dept,
            "p_channel": channel,
            "p_objective": objective,
            "p_limit": 20
        }).execute()
        return result.data or []
    except Exception:
        return []


def determine_variation_count(budget_tier: str) -> int:
    return {"test": 2, "scale": 3, "aggressive": 5}.get(budget_tier, 3)

# ── Agent prompts ──────────────────────────────────────────────────────────────

A1_SYSTEM = """
You are a Context Normalization Agent.

Structure the input. Do NOT block execution except when objective is missing or fully ambiguous.
Assign input_confidence (0–100) based on completeness and specificity.
Document all assumptions in warnings[].

Budget tier rules:
- under ₹2L = "test"
- ₹2L–₹20L = "scale"  
- above ₹20L = "aggressive"
- if no budget mentioned = "scale" (warn)

Risk profile rules:
- test budget → "conservative"
- scale budget → "balanced"
- aggressive budget → "high"
- kpi_pressure=aggressive overrides to "high" regardless of budget

Output this exact JSON structure with no additional fields.
"""

A2_SYSTEM = """
You are a Memory-Augmented Data Intelligence Agent.

Analyze the retrieved memory context and any uploaded campaign data.
Extract patterns, detect fatigue signals, and identify conflicts between metrics.

Conflict detection rules:
- If urgency/scarcity patterns score high on CTR but low on CVR, flag as CTR_vs_CVR conflict
- If a hook_type appears in 5+ consecutive campaigns for a segment, flag as fatigue
- If channel performance data contradicts memory patterns, flag as channel_mismatch

Output pattern_conflicts[] with resolution_recommendation for each conflict.
Output avoid_patterns[] as clear strings A4 can follow directly.
Do NOT generate any copy. Analysis only.
"""

A3_SYSTEM = """
You are a Marketing Strategy Engine.

Read pattern_conflicts[] and document your resolution in conflict_resolution.
Read budget_tier and risk_profile from context:
- conservative = proven hooks only (TRUST, CONVENIENCE, REWARD)
- balanced = add one experimental hook type  
- high = full range, experimental angles encouraged

Output strategy_confidence (0–100) honestly. Low confidence is useful signal.
No copywriting. No generic advice. Tie everything to the stated objective.
"""

A3_5_SYSTEM = """
You are a Strategy Validation Agent.

Check if the strategy:
1. Aligns with the stated primary_metric objective
2. Documents resolution for any pattern conflicts
3. Does not use aggressive hooks (URGENCY, SCARCITY) on a conservative risk profile
4. Has a strategy_confidence score (not missing)

If issues are found, provide a specific suggested_fix.
Do NOT rewrite the strategy — only validate it.
"""

A4_SYSTEM = """
You are a Performance Copywriting Agent.

Generate exactly {variation_count} variations. Each must have a DISTINCT hook_type.
Tag each variation at source using ONLY these controlled values:
- hook_type: URGENCY | SCARCITY | TRUST | CONVENIENCE | REWARD | IDENTITY | OTHER
- tone: FUNCTIONAL | WARM | URGENT | ASPIRATIONAL | REASSURING | PLAYFUL
- offer_type: CASHBACK_FLAT | CASHBACK_PCT | LOYALTY_REWARD | REFERRAL | TRIAL_FREE | NO_OFFER
- cta_type: DIRECT | SOFT | URGENCY_DRIVEN | BENEFIT_LED

If hook_type = OTHER, hook_subtype is required (max 30 chars).
Avoid ALL patterns listed in avoid_patterns[].
Follow character limits: headline ≤ 60, description ≤ 90, CTA ≤ 20.
"""

A5_SYSTEM = """
You are a Content Validator.

Score content 0–100. Route based on score:
- ≥ 70: PASS
- 50–69: SOFT_RETRY (copy execution issue)
- < 50: ESCALATE (strategy issue)

Categorize issues as critical (char limit breach, policy), moderate (weak CTA, generic copy), minor (stylistic).
Do NOT over-penalize minor issues.
Do NOT rewrite content — only score and categorize.
Include fail_reason as a short category string: tone_mismatch | weak_cta | char_limit | policy_breach | low_differentiation | generic_copy
"""

A6_SYSTEM = """
You are an Experimentation Planning Agent.

Design a practical A/B test plan for the validated creatives.
Scale the test structure to budget_tier:
- test: 2-arm, single variable
- scale: 2–3 arm, 1–2 variables
- aggressive: full factorial if justified by budget

Output the memory_write payload with all required fields tagged.
Keep test_plan to one concise sentence.
"""

# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(brief: dict, dept: str) -> dict:
    """
    Main pipeline runner. Returns full output dict.
    All non-LLM steps are called as functions.
    """
    run_log = {"dept": dept, "started_at": datetime.utcnow().isoformat(), "llm_calls": 0}

    # ── A1: Soft Normalizer ────────────────────────────────────────────────────
    print("A1: Normalizing input...")
    context = llm(A1_SYSTEM, f"Input brief:\n{json.dumps(brief, indent=2)}")
    run_log["llm_calls"] += 1

    if not context.get("objective") or not context["objective"].get("primary_metric"):
        return {"error": "OBJECTIVE_REQUIRED", "message": "Campaign objective is missing. Please specify primary_metric (CTR, CVR, INSTALL, or LTV)."}

    context["dept"] = dept

    # ── A2: Memory + Data Intelligence ────────────────────────────────────────
    print("A2: Reading memory and analyzing patterns...")
    memory_data = read_memory(dept, context.get("channels", [""])[0], 
                               context["objective"]["primary_metric"])

    has_data = bool(memory_data) or brief.get("historical_data")
    if has_data:
        intelligence = llm(
            A2_SYSTEM,
            f"Context:\n{json.dumps(context, indent=2)}\n\nMemory data:\n{json.dumps(memory_data, indent=2)}"
        )
        run_log["llm_calls"] += 1
    else:
        print("  → No memory data. A2 skipped.")
        intelligence = {
            "top_patterns": [], "bad_patterns": [], "avoid_patterns": [],
            "pattern_conflicts": [], "fatigue_detected": False,
            "insight_confidence": 0,
            "warnings": ["No historical data — strategy uses general best practices"]
        }

    # ── A3: Strategy Engine ────────────────────────────────────────────────────
    print("A3: Generating strategy...")
    strategy = llm(
        A3_SYSTEM,
        f"Context:\n{json.dumps(context, indent=2)}\n\nIntelligence:\n{json.dumps(intelligence, indent=2)}"
    )
    run_log["llm_calls"] += 1

    # ── A3.5: Strategy Validator (function first) ──────────────────────────────
    print("A3.5: Validating strategy...")
    strategy_validation = validate_strategy_schema(strategy, intelligence)

    if not strategy_validation["is_valid"]:
        print(f"  → Schema issues found: {strategy_validation['issues']}. Revising strategy with LLM...")
        strategy = llm(
            A3_5_SYSTEM,
            f"Strategy:\n{json.dumps(strategy, indent=2)}\n\nIntelligence:\n{json.dumps(intelligence, indent=2)}\n\nIssues to fix:\n{strategy_validation['issues']}"
        )
        run_log["llm_calls"] += 1
        # Hard pass after one revision — don't loop A3 again

    # ── A4: Content Generator ──────────────────────────────────────────────────
    variation_count = determine_variation_count(context.get("budget_tier", "scale"))
    a4_prompt = A4_SYSTEM.format(variation_count=variation_count)

    def generate_content(escalation_reason=None, tag_correction=None):
        extra = ""
        if escalation_reason:
            extra += f"\n\nEscalation context: {escalation_reason}"
        if tag_correction:
            extra += f"\n\nTag corrections needed: {tag_correction}"
        result = llm(
            a4_prompt,
            f"Strategy:\n{json.dumps(strategy, indent=2)}\n\nAvoid patterns: {intelligence.get('avoid_patterns', [])}{extra}"
        )
        run_log["llm_calls"] += 1
        return result

    print("A4: Generating content...")
    content = generate_content()

    # Tag validation (function — not LLM)
    tag_errors = validate_tags(content)
    if tag_errors:
        print(f"  → Tag errors found: {tag_errors}. Correcting...")
        content = generate_content(tag_correction=tag_errors)

    # ── A5: Score-Banded Validator ─────────────────────────────────────────────
    print("A5: Validating content...")
    retry_count = 0
    last_fail_reason = None
    score_result = {"score": 0, "status": "PENDING"}

    while retry_count <= MAX_RETRY_CYCLES:
        score_result = llm(
            A5_SYSTEM,
            f"Content:\n{json.dumps(content, indent=2)}\n\nObjective: {context['objective']}\n\nStrategy:\n{json.dumps(strategy, indent=2)}"
        )
        run_log["llm_calls"] += 1
        score_result["retry_count"] = retry_count
        score = score_result.get("score", 0)

        if score >= 70:
            print(f"  → PASS (score: {score})")
            break

        if retry_count >= MAX_RETRY_CYCLES:
            score_result["status"] = "HUMAN_REVIEW"
            print(f"  → Max retries reached. Flagging for human review.")
            break

        fail_reason = score_result.get("fail_reason")

        if fail_reason == last_fail_reason:
            # Same reason twice = escalate immediately
            print(f"  → Same fail reason twice ({fail_reason}). Escalating to A3...")
            strategy = llm(
                A3_SYSTEM,
                f"Context:\n{json.dumps(context, indent=2)}\n\nIntelligence:\n{json.dumps(intelligence, indent=2)}\n\nEscalation reason: {fail_reason}\n\nPrior validator output:\n{json.dumps(score_result, indent=2)}"
            )
            run_log["llm_calls"] += 1
            content = generate_content(escalation_reason=fail_reason)
        elif score >= 50:
            print(f"  → SOFT_RETRY (score: {score}, reason: {fail_reason})")
            content = generate_content()
        else:
            print(f"  → ESCALATE to A3 (score: {score}, reason: {fail_reason})")
            strategy = llm(
                A3_SYSTEM,
                f"Context:\n{json.dumps(context, indent=2)}\n\nIntelligence:\n{json.dumps(intelligence, indent=2)}\n\nEscalation reason: {fail_reason}"
            )
            run_log["llm_calls"] += 1
            content = generate_content(escalation_reason=fail_reason)

        last_fail_reason = fail_reason
        retry_count += 1

    # ── A6: Experiment Planner + Memory Write ──────────────────────────────────
    print("A6: Planning experiment...")
    plan = llm(
        A6_SYSTEM,
        f"Content:\n{json.dumps(content, indent=2)}\n\nContext:\n{json.dumps(context, indent=2)}\n\nValidator score: {score_result.get('score')}"
    )
    run_log["llm_calls"] += 1

    # Memory write — function call, not LLM
    print("Writing to memory store...")
    memory_payload = {
        "dept": dept,
        "campaign_id": brief.get("campaign_id", f"campaign_{datetime.utcnow().timestamp()}"),
        "hook_type": strategy.get("primary_hook"),
        "tone": strategy.get("tone"),
        "offer_type": strategy.get("offer_strategy"),
        "channel": context.get("channels", [""])[0],
        "audience_type": brief.get("audience_type", ""),
        "funnel_stage": brief.get("funnel_stage", ""),
        "objective_type": context["objective"]["primary_metric"],
        "conflict_resolution": strategy.get("conflict_resolution"),
        "validator_score": score_result.get("score"),
        "performance_outcome": None,  # populated after campaign results come in
    }
    memory_written = write_memory(memory_payload)
    plan["memory_written"] = memory_written

    run_log["completed_at"] = datetime.utcnow().isoformat()
    run_log["final_score"] = score_result.get("score")

    # ── Final output ───────────────────────────────────────────────────────────
    return {
        "status": score_result.get("status", "PASS"),
        "context": context,
        "strategy": strategy,
        "content": content,
        "validation": score_result,
        "experiment_plan": plan,
        "run_log": run_log
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sample_brief = {
        "campaign_id": "WAL-2024-001",
        "business_unit": "Wallet",
        "campaign_type": "Cashback promotion",
        "target_audience": "Repeat users, last active 7–30 days",
        "objective": {"primary_metric": "CTR", "priority": "scale"},
        "channels": ["SMS", "PUSH"],
        "budget": "500000",
        "campaign_maturity": "scaling",
        "kpi_pressure": "balanced",
        "audience_type": "REPEAT",
        "funnel_stage": "RETENTION"
    }

    result = run_pipeline(sample_brief, dept="wallet")
    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print(f"Final score: {result['run_log'].get('final_score')}")
    print(f"LLM calls: {result['run_log'].get('llm_calls')}")
    print(f"Status: {result['status']}")
    print("="*60)
    print(json.dumps(result["content"], indent=2))
