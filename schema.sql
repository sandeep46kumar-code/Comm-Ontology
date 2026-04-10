-- Marketing Intelligence System — Memory Store Schema
-- Run via: supabase db push
-- Requires: pgvector extension

-- Enable vector extension (Supabase enables this by default on paid plans)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Main memory table ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS campaign_memory (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Namespace (strict isolation per department)
  dept                TEXT NOT NULL,
  campaign_id         TEXT NOT NULL,
  
  -- Ontology tags (controlled vocab — enforced at application layer)
  hook_type           TEXT NOT NULL CHECK (hook_type IN ('URGENCY','SCARCITY','TRUST','CONVENIENCE','REWARD','IDENTITY','OTHER')),
  hook_subtype        TEXT CHECK (char_length(hook_subtype) <= 30),
  tone                TEXT NOT NULL CHECK (tone IN ('FUNCTIONAL','WARM','URGENT','ASPIRATIONAL','REASSURING','PLAYFUL')),
  offer_type          TEXT NOT NULL CHECK (offer_type IN ('CASHBACK_FLAT','CASHBACK_PCT','LOYALTY_REWARD','REFERRAL','TRIAL_FREE','NO_OFFER')),
  cta_type            TEXT CHECK (cta_type IN ('DIRECT','SOFT','URGENCY_DRIVEN','BENEFIT_LED')),
  audience_type       TEXT CHECK (audience_type IN ('NEW','REPEAT','HIGH_INTENT','LOW_INTENT')),
  funnel_stage        TEXT CHECK (funnel_stage IN ('ACQUISITION','ACTIVATION','RETENTION')),
  channel             TEXT NOT NULL CHECK (channel IN ('SMS','WHATSAPP','EMAIL','SEARCH','UAC','PMAX','DEMAND_GEN','IN_APP','PUSH')),
  objective_type      TEXT NOT NULL CHECK (objective_type IN ('CTR','CVR','INSTALL','LTV')),
  creative_format     TEXT CHECK (creative_format IN ('TEXT','IMAGE','VIDEO','CAROUSEL')),
  conflict_resolution TEXT CHECK (conflict_resolution IN ('CTR_BIAS','CVR_BIAS','BALANCED','NOT_APPLICABLE')),
  
  -- Scoring
  validator_score     INTEGER NOT NULL CHECK (validator_score BETWEEN 0 AND 100),
  
  -- Performance (populated after campaign results)
  performance_outcome JSONB DEFAULT NULL,
  -- Structure: {"ctr": 0.042, "cvr": 0.018, "installs": null, "ltv": null, "measured_at": "2024-01-15"}
  
  -- Decay and weighting
  decay_weight        FLOAT DEFAULT 1.0 CHECK (decay_weight BETWEEN 0.0 AND 1.0),
  -- Decremented by 0.05 each read cycle where pattern is surfaced but not selected
  
  -- Semantic search vector (1536-dim for text-embedding-3-small)
  embedding           VECTOR(1536),
  
  -- Timestamps
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ────────────────────────────────────────────────────────────────────

-- Primary retrieval path (A2 reads by dept + channel + objective)
CREATE INDEX IF NOT EXISTS idx_memory_dept_channel_obj 
  ON campaign_memory(dept, channel, objective_type);

-- Secondary path for pattern analysis
CREATE INDEX IF NOT EXISTS idx_memory_dept_hook 
  ON campaign_memory(dept, hook_type);

-- Recency queries
CREATE INDEX IF NOT EXISTS idx_memory_created 
  ON campaign_memory(dept, created_at DESC);

-- Vector index for semantic retrieval (HNSW — better for read-heavy workloads)
CREATE INDEX IF NOT EXISTS idx_memory_embedding 
  ON campaign_memory USING hnsw (embedding vector_cosine_ops);

-- ── Weighted pattern retrieval function ───────────────────────────────────────
-- Called by A2's read_memory() — not an LLM call

CREATE OR REPLACE FUNCTION get_weighted_patterns(
  p_dept        TEXT,
  p_channel     TEXT,
  p_objective   TEXT,
  p_limit       INTEGER DEFAULT 20
)
RETURNS TABLE (
  hook_type           TEXT,
  tone                TEXT,
  offer_type          TEXT,
  conflict_resolution TEXT,
  validator_score     INTEGER,
  performance_outcome JSONB,
  decay_weight        FLOAT,
  relevance_score     FLOAT,
  created_at          TIMESTAMPTZ
)
LANGUAGE SQL STABLE AS $$
  SELECT
    hook_type,
    tone,
    offer_type,
    conflict_resolution,
    validator_score,
    performance_outcome,
    decay_weight,
    -- Relevance = 40% validator score + 40% performance (if available) + 20% recency
    (
      (validator_score::float / 100.0) * 0.40
      + COALESCE((performance_outcome->>'ctr')::float * 10, 0) * 0.40
      + (decay_weight * (1.0 / (EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400 + 1))) * 0.20
    ) AS relevance_score,
    created_at
  FROM campaign_memory
  WHERE
    dept = p_dept
    AND channel = p_channel
    AND objective_type = p_objective
    AND decay_weight > 0.1  -- exclude fully decayed records
  ORDER BY relevance_score DESC
  LIMIT p_limit;
$$;

-- ── Decay update function ──────────────────────────────────────────────────────
-- Run weekly via cron or Supabase edge function scheduler

CREATE OR REPLACE FUNCTION apply_memory_decay(
  p_dept          TEXT DEFAULT NULL,  -- NULL = all departments
  p_decay_amount  FLOAT DEFAULT 0.05
)
RETURNS INTEGER  -- returns count of records updated
LANGUAGE PLPGSQL AS $$
DECLARE
  updated_count INTEGER;
BEGIN
  UPDATE campaign_memory
  SET 
    decay_weight = GREATEST(0.0, decay_weight - p_decay_amount),
    updated_at = NOW()
  WHERE
    (p_dept IS NULL OR dept = p_dept)
    AND created_at < NOW() - INTERVAL '7 days'  -- only decay records older than 7 days
    AND decay_weight > 0.0;
  
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count;
END;
$$;

-- ── Performance update function ────────────────────────────────────────────────
-- Called when campaign results come in (manual upload or auto-sync)

CREATE OR REPLACE FUNCTION update_performance(
  p_campaign_id       TEXT,
  p_dept              TEXT,
  p_performance       JSONB  -- {"ctr": 0.042, "cvr": 0.018, "measured_at": "2024-01-15"}
)
RETURNS BOOLEAN
LANGUAGE PLPGSQL AS $$
BEGIN
  UPDATE campaign_memory
  SET
    performance_outcome = p_performance,
    updated_at = NOW()
  WHERE campaign_id = p_campaign_id AND dept = p_dept;
  
  RETURN FOUND;
END;
$$;

-- ── Ontology audit view ────────────────────────────────────────────────────────
-- Surfaces hook_subtype values that appear 3+ times (candidates for ontology promotion)

CREATE OR REPLACE VIEW ontology_promotion_candidates AS
  SELECT
    dept,
    hook_subtype,
    COUNT(*) as usage_count,
    AVG(validator_score) as avg_validator_score,
    MAX(created_at) as last_used
  FROM campaign_memory
  WHERE hook_type = 'OTHER' AND hook_subtype IS NOT NULL
  GROUP BY dept, hook_subtype
  HAVING COUNT(*) >= 3
  ORDER BY usage_count DESC;

-- ── Row-level security (Supabase) ─────────────────────────────────────────────
-- Ensures department isolation at database level

ALTER TABLE campaign_memory ENABLE ROW LEVEL SECURITY;

-- Each department's service role only sees its own namespace
-- In production: use Supabase Auth JWT claims to enforce dept
CREATE POLICY dept_isolation ON campaign_memory
  FOR ALL
  USING (dept = current_setting('app.current_dept', true));

-- ── Sample data for testing ───────────────────────────────────────────────────

INSERT INTO campaign_memory (
  dept, campaign_id, hook_type, tone, offer_type, cta_type,
  audience_type, funnel_stage, channel, objective_type,
  conflict_resolution, validator_score,
  performance_outcome, decay_weight
) VALUES
(
  'wallet', 'WAL-2024-001', 'URGENCY', 'FUNCTIONAL', 'CASHBACK_FLAT', 'URGENCY_DRIVEN',
  'REPEAT', 'RETENTION', 'SMS', 'CTR',
  'CTR_BIAS', 78,
  '{"ctr": 0.041, "measured_at": "2024-01-10"}', 0.95
),
(
  'wallet', 'WAL-2024-002', 'TRUST', 'WARM', 'NO_OFFER', 'SOFT',
  'NEW', 'ACQUISITION', 'WHATSAPP', 'CVR',
  'CVR_BIAS', 71,
  '{"cvr": 0.022, "measured_at": "2024-01-12"}', 0.90
),
(
  'wallet', 'WAL-2024-003', 'REWARD', 'FUNCTIONAL', 'CASHBACK_PCT', 'BENEFIT_LED',
  'HIGH_INTENT', 'ACTIVATION', 'PUSH', 'CTR',
  'NOT_APPLICABLE', 65,
  '{"ctr": 0.028, "measured_at": "2024-01-14"}', 0.85
);
