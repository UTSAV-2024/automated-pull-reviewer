# Product specification — automated-pull-reviewer

> Status: draft. A coding agent must not implement product code until this specification is approved through Genesis.

## Problem

Manual pull-request review is slow (PRs queue on senior-engineer attention), inconsistent (the same bug class is caught one day and missed the next), and wastes scarce senior time on mechanical pattern-recognition (missing null guards, unhandled exceptions, missing tests, undocumented public APIs) instead of judgment calls that actually require a human.

This system exists to reclaim scarce senior-reviewer attention by automating the mechanical part of code review, so a human is spent only where real judgment is required.

Source: "Designing an AI Pull-Request Review Agent" (antern.co, 2026-07-22), summarized in the user-provided project explainer PDF.

## Users

- **PR authors**: developers who open pull requests and receive review findings inline on GitHub.
- **Senior/human reviewers**: receive escalated findings (CRITICAL severity, or below-confidence-threshold findings) via a human approval queue; can dispute a posted finding.
- **Repo/org admins**: configure the daily LLM budget cap and monitor spend via the dashboard.

## Functional requirements

- FR-1: The system receives GitHub `pull_request` webhook events (opened, synchronize), verifies the HMAC-SHA256 signature, and rejects requests with an invalid or missing signature.
- FR-2: The webhook ingress deduplicates by GitHub delivery ID (idempotency key) and returns `200 OK` immediately, without performing review work inline.
- FR-3: Accepted review jobs are enqueued to a Redis + ARQ queue for asynchronous processing.
- FR-4: A LangGraph orchestrator fans a queued review job out to four specialist agents — security, quality, tests, docs — run in parallel.
- FR-5: Each specialist agent retrieves relevant codebase context via hybrid retrieval (vector similarity search fused with keyword/full-text search, via Reciprocal Rank Fusion) before reasoning over the diff, and returns structured Findings with fields: `agent_type`, `severity`, `category`, `file`, `line`, `confidence`, `rationale`.
- FR-6: An aggregator node waits for all four specialists to finish, merges their findings, removes duplicate/overlapping findings raised by more than one specialist, and computes one overall confidence score for the review.
- FR-7: A confidence-weighted HITL gate applies these rules in order: (a) any CRITICAL-severity finding escalates to a human queue regardless of confidence; (b) confidence below a configured threshold routes to a human approval queue; (c) otherwise the review posts to GitHub automatically.
- FR-8: Auto-posted or human-approved reviews are posted back to GitHub as a structured review with findings attached to specific files and lines.
- FR-9: A developer can dispute a posted finding; disputes are recorded as feedback and require a minimum evidence threshold before they influence future agent behavior (defense against feedback-loop poisoning).
- FR-10: Every agent action (span start/end, LLM call, tool call, decision) is written as an append-only row to a single time-ordered events table, sufficient to reconstruct any one review end-to-end for a trace viewer and audit trail.
- FR-11: A BudgetGuard checks a live cost rollup before each LLM call and hard-blocks new LLM calls once a configured daily spend cap is reached.

## Non-functional requirements

- NFR-1: The webhook endpoint responds within 2 seconds regardless of downstream review processing time (fast ack, work is queued not inline).
- NFR-2: Workflow state is checkpointed at each orchestration node boundary so a crashed worker resumes a review from its last completed node rather than restarting it.
- NFR-3: Duplicate webhook deliveries for the same GitHub delivery ID never result in a duplicate posted review (idempotency + dedup-before-posting).
- NFR-4: Every specialist LLM call is grounded in retrieved codebase context; no specialist reasons from the diff alone.
- NFR-5: Every agent action is logged to an immutable-by-construction event store; a single review must be fully reconstructable from it.
- NFR-6: Daily LLM spend is capped and the cap is enforced before further cost is incurred, not after the fact.
- NFR-7: Each orchestration node carries a timeout; a hung specialist must not block the aggregator join indefinitely (no orchestration deadlock).
- NFR-8: On timeout or tool/API failure, the system retries with backoff and applies circuit breakers, degrading to "slower but correct," never posting an incomplete or fabricated review as if it were complete.

## Constraints

- Source integration is GitHub (App/webhooks) — not GitLab, Bitbucket, or other VCS, for v1.
- Data store is Tiger Cloud (managed Postgres + TimescaleDB + pgvector/pgvectorscale), per explicit user decision, carrying vector memory, relational truth, and time-series events in one store. Redis is used only for the ephemeral job queue and LangGraph checkpointing.
- Orchestration uses LangGraph, kept behind a narrow interface (`core/workflow_engine.py`) so it can be swapped later (ADR-001).
- Architecture is a modular monolith (single deployed process, internally bounded modules with an inward-only dependency rule), not microservices, until a measured bottleneck justifies splitting (ADR-002).
- v1 scope is the MVP core loop only (see Non-goals) — this corresponds roughly to phases 0–8 of the source document's 20-phase roadmap.

## Non-goals

- Full 20-phase production build (evaluation harness with golden datasets, full observability/tracing dashboard, security threat-modeling/RBAC hardening, governance/data-residency, economics dashboard, developer-experience tooling, CI/CD-for-AI, continuous learning/drift detection) is **out of scope for v1**. These map to later phases/tasks, not this specification.
- Full production dashboard (Next.js review dashboard, trace viewer, economics page) is out of scope for v1; a minimal way to see HITL-queued items is in scope, full UI is not.
- Multi-tenant SaaS support for arbitrary third-party repositories is out of scope; v1 targets a single connected repository.
- Automatic model fine-tuning or continuous learning from disputes is out of scope; disputes are recorded but only manually reviewed in v1.
- Splitting into microservices (separate ingress service, separate worker pool) is explicitly deferred until a measured scale bottleneck (per ADR-002).

## Acceptance criteria

- AC-1: Given a PR is opened or synchronized, when the webhook fires with a valid HMAC signature, the system returns `200 OK` and enqueues exactly one review job.
- AC-2: Given a duplicate delivery of the same webhook (same GitHub delivery ID), when it is received, no second review job is enqueued and no duplicate review is posted.
- AC-3: Given a queued review job, when it completes, all four specialists (security, quality, tests, docs) have produced findings with `agent_type`, `severity`, `category`, `file`, `line`, `confidence`, and `rationale` populated.
- AC-4: Given aggregated findings with confidence at or above the configured threshold and no CRITICAL-severity finding, when the HITL gate evaluates them, the review posts to GitHub automatically without human action.
- AC-5: Given any CRITICAL-severity finding, when the HITL gate evaluates the aggregated result, the review is routed to the human queue and is not auto-posted, regardless of confidence.
- AC-6: Given any specialist LLM call, when it executes, the event log shows retrieved code context was included in that call's prompt (grounding is verifiable, not asserted).
- AC-7: Given the daily budget cap has been reached, when a new LLM call is attempted, BudgetGuard blocks it and the block is visible in the event log.
- AC-8: Given a worker crashes mid-review, when it (or a replacement worker) resumes, the review continues from the last completed orchestration node rather than restarting from the beginning.

## Risks

- **Prompt injection via PR diff content.** The diff is attacker-controlled text placed directly into specialist prompts; a malicious PR could attempt to manipulate an agent (e.g., the security specialist) into approving itself. Mitigation approach is unresolved — flagged as an open question, must be addressed before any auto-post path is trusted in production.
- **Unvalidated confidence calibration.** Confidence scores are self-reported by the model; a stated 0.8 may not mean 80% correct. Poor calibration could cause the HITL gate to over- or under-trigger.
- **Cost overrun.** LLM calls at volume are expensive; BudgetGuard caps daily spend but the cap value and escalation policy for blocked PRs are undefined (open question).
- **Vendor/dependency risk.** Tiger Cloud, LangGraph, and the GitHub App integration are all third-party dependencies the system's core loop depends on.
- **Idempotency race condition.** A GitHub webhook redelivered after a review posts but before completion is recorded could theoretically double-post; needs an explicit sequence (open question in source material).

## Open questions

- What confidence threshold value defines "high confidence" (auto-post) vs. "route to human"? No default is specified in the source material.
- What is the daily LLM budget cap value, and what happens to a PR that arrives after the cap is hit — queued, rejected, or silently skipped?
- Which specific LLM model(s) power each specialist ("model-routed per agent" is stated, but models are unspecified)?
- What is the mitigation strategy for prompt injection via PR diff content into the security specialist's prompt?
- Is this repository the only repo under review, or should the design anticipate more repos being connected later (affects the repo_file_index / ingestion scope)?
- Deployment target: Railway (as in the source doc) — confirmed or open to change?
