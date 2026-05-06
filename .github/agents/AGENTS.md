# Custom Agents for Contract-Sweeper

This directory contains specialized agents for the Puerto Rico Federal Contracts Data Pipeline.

## Available Agents

### data-source-audit.agent.md
**Purpose**: Audit financial data source completeness, detect coverage gaps, and ensure exhaustive optimization across all 35+ download scripts.

**Invoke when**:
- Auditing all data sources for gaps and coverage
- Debugging individual source failures (FPDS, FEMA PA, HUD DRGR, PR Comptroller, Act 60, etc.)
- Running selective updates (full pipeline vs. contracts-only, etc.)
- Monitoring source health and freshness
- Suggesting new financial datasets fitting the project pattern
- Optimizing parallel fetch opportunities
- Validating fiscal year coverage (especially 2007)

**Key capabilities**:
- Inventory all 35+ financial sources across 7 categories
- Detect missing fiscal years, dead endpoints, stale data
- Suggest parallel fetching opportunities
- Debug API failures, rate limits, certification issues
- Recommend new datasets (COR3, DTOP, DRNA, P3A, AFAAF, etc.)
- Validate PR-specific sources (Comptroller, Act 60, cabilderos, utilities, pensions)
- Distinguish between permanent gaps vs. temporary unavailability

**Example prompts**:
- "Audit completeness: are all 35 data sources working?"
- "Debug the 2007 fiscal year gap in FPDS"
- "Run only contracts + grants, what flags do I need?"
- "Find PR sources with stale data (>60 days old)"
- "Suggest new financial datasets for PR political economy"
- "Which downloads can run in parallel to optimize?"
- "Monitor source health: what's failing and why?"
