# Enterprise Agentic Web - Top 20 Features and User Stories (v1.1.0-features)

Personas: **Priya** (Business Analyst), **Arjun** (Finance Manager), **Meera** (Compliance Officer), **Kiran** (Agent Owner), **Sam** (Platform Admin).
Status: **Built** = already in the POC before v1.1 · **New v1.1** = added in this release. Every feature has an automated test.

| # | Feature | Status | Where |
|---|---|---|---|
| 1 | Intent-based agent discovery | Built | Marketplace, Ask → Preview · `POST /api/discover` |
| 2 | Multi-agent composition and one consolidated result | Built | Ask · `POST /api/runs` |
| 3 | Human approval inbox (HITL) | Built (v1.0) | Approvals tab · `GET /api/approvals` |
| 4 | Zero-trust policy decision per step | Built | Ask → Policy decision |
| 5 | Scoped delegation (no permission inheritance) | Built | Ask → Policy decision |
| 6 | Agent registration with validation | Built | Register Agent · `POST /api/agents` |
| 7 | Lifecycle certification gate | Built | Marketplace → Details → Promote |
| 8 | Policy simulator | Built | Governance & Audit |
| 9 | Immutable-style audit trail | Built | Governance & Audit · `GET /api/audit` |
| 10 | Pilot KPI observability | Built | Observability · `GET /api/metrics` |
| 11 | Budget and quota guard | Built | Header budget, policy check |
| 12 | Provider abstraction layer (5 providers) | Built | `app/adapters.py` |
| 13 | Explainable access preview | Built | Marketplace cards and details |
| 14 | Approval comments and rejection reasons | **New v1.1** | Approve/Reject prompts · `decision.comment` |
| 15 | Bulk approvals | **New v1.1** | Approvals → Select all · `POST /api/approvals/bulk` |
| 16 | Run history | **New v1.1** | My Runs tab · `GET /api/runs` |
| 17 | Agent ratings and feedback | **New v1.1** | Ask → Rate ★ · `POST /api/runs/{id}/feedback` |
| 18 | Agent kill switch | **New v1.1** | Marketplace → Details (Admin) · `POST /api/agents/{id}/suspend` |
| 19 | Run report download | **New v1.1** | Ask → Download report · `GET /api/runs/{id}/report` |
| 20 | Audit log CSV export | **New v1.1** | Governance → Export CSV · `GET /api/audit/export` |

---

## 1. Intent-based agent discovery
**As** Priya, **I want** to describe a business need in plain language **so that** I find the right agent without knowing agent names.
- Results are ranked by relevance with matched terms.
- "Check customer onboarding documents" ranks the KYC agent first.
- Each result shows whether I can use it.
Test: `test_discovery_by_intent`

## 2. Multi-agent composition and one consolidated result
**As** Priya, **I want** the platform to select and sequence several agents for my intent **so that** I get one readiness verdict instead of six separate outputs.
- Up to 6 agents, ordered by stage.
- Vague spec → "Not ready"; well-specified spec → "Ready for development".
- Totals for agents run, cost, tokens and latency are shown.
Test: `test_multi_agent_run_bad_vs_good_spec`

## 3. Human approval inbox
**As** Meera, **I want** every agent run that needs sign-off to wait in one inbox **so that** consequential actions never run without a human.
- Finance and KYC agents pause with status `awaiting_approval`.
- The Approvals tab shows a count badge and a card per paused step.
- Only the requester, a Compliance Officer or a Platform Admin can decide. Others get 403.
Tests: `test_human_approval_flow`, `test_kyc_run_appears_in_meera_inbox_and_she_can_approve`, `test_business_analyst_sees_no_one_elses_approvals_and_cannot_decide`

## 4. Zero-trust policy decision per step
**As** Meera, **I want** each agent call evaluated against identity, role, region, classification, lifecycle, kill switch, resources and budget **so that** I can see exactly why it was allowed or denied.
- Every step stores its list of checks.
- The first failing check becomes the visible reason.
Test: `test_rbac_blocks_and_audits`

## 5. Scoped delegation
**As** Sam, **I want** agents to receive only their declared resource scopes **so that** an agent never inherits the user's or upstream agents' permissions.
- `inherits_user_permissions` and `inherits_upstream_agent_permissions` are always false.
Test: `test_delegation_is_scoped`

## 6. Agent registration
**As** Kiran, **I want** to register an agent through a validated form **so that** it enters the catalog with ownership and policy metadata.
- Only Agent Owners and Platform Admins can register.
- Duplicate or invalid IDs are rejected with field-level errors.
Test: `test_registration_and_lifecycle_gate`

## 7. Lifecycle certification gate
**As** Sam, **I want** to promote agents one step at a time through Validated → Certified → Production **so that** uncertified agents cannot be invoked.
- Skipping a stage returns 409.
- A Registered agent is blocked until it reaches Certified.
Test: `test_registration_and_lifecycle_gate`

## 8. Policy simulator
**As** Meera, **I want** to test whether any user can invoke any agent **so that** I can validate access rules before an audit.
- Shows every check, including role and region failures.
Test: `test_policy_simulation_region_abac`

## 9. Audit trail
**As** Meera, **I want** every invocation, approval request, decision, registration, promotion and suspension logged **so that** I can reconstruct who did what.
- Compliance Officers and Admins see all events; other users see only their own.
- The log can be filtered by action.
Tests: `test_rbac_blocks_and_audits`, `test_rejected_step_never_executes_and_is_audited`

## 10. Pilot KPI observability
**As** Sam, **I want** pilot KPIs against targets (agents onboarded, providers, discovery >90%, execution >95%) **so that** I can report pilot success.
- Cost, tokens and latency are shown per agent.
Test: `test_metrics_kpis`

## 11. Budget and quota guard
**As** Sam, **I want** each user to have a spend budget **so that** agent costs cannot run away.
- A call is blocked when remaining budget is below the call cost.
- Remaining budget is shown in the header.
Test: `test_budget_quota`

## 12. Provider abstraction layer
**As** Kiran, **I want** one normalized contract across Neuro SAN, NANDA-inspired, Otari, AWS Bedrock and Enterprise API **so that** consumers don't depend on a provider.
- Swapping a provider only touches `app/adapters.py`.
Test: covered by all run tests

## 13. Explainable access preview
**As** Priya, **I want** to see before running whether I can use an agent, and why not **so that** I don't hit unexplained failures.
- Marketplace cards show "You can use this agent" or the failing policy reason.
Test: `test_catalog_size_and_access_preview`

## 14. Approval comments and rejection reasons — New v1.1
**As** Meera, **I want** to add a comment when I approve and a reason when I reject **so that** the audit shows why a decision was made.
- The UI always asks for a reason (at least 3 characters) to reject.
- The comment is stored on the step, shown in the run and written to the audit `reason`.
- Set `POC_REQUIRE_REJECT_REASON=true` to enforce the reason for API clients too.
Test: `test_reject_requires_reason_and_comment_is_recorded`

## 15. Bulk approvals — New v1.1
**As** Meera, **I want** to approve or reject several pending steps at once **so that** I can clear a backlog quickly.
- Select all or individual cards; buttons show the selected count.
- Each item is permission-checked; per-item success or failure is returned (partial success allowed).
Tests: `test_bulk_approve_partial_success`, `test_bulk_respects_permissions`

## 16. Run history — New v1.1
**As** Arjun, **I want** a list of my past runs with status **so that** I can reopen results and finish pending approvals.
- Filter by status; Open reloads the full run in the Ask tab.
- Compliance Officers and Admins see all runs.
Test: UI marker test `test_ui_has_v11_controls` and browser click-through

## 17. Agent ratings and feedback — New v1.1
**As** Priya, **I want** to rate an agent 1–5 after it completes **so that** agent owners get quality signals.
- Only the run owner can rate, only completed steps, and a re-rating replaces the earlier one.
- Agent details show the average and count.
Test: `test_feedback_only_for_completed_steps_and_aggregates`

## 18. Agent kill switch — New v1.1
**As** Sam, **I want** to suspend a misbehaving agent immediately, with a reason **so that** no new invocations run during an incident.
- Suspension adds a failing "Kill switch" policy check showing the reason.
- Resume restores access. Both actions are audited. Only Platform Admin can use it.
Test: `test_kill_switch_blocks_and_resumes`

## 19. Run report download — New v1.1
**As** Arjun, **I want** to download a run as a Markdown report **so that** I can attach it to a decision record.
- Includes intent, status, headline, each step, human decision with comment, scopes and recommendations.
- Only users who can view the run can download it.
Test: `test_run_report_markdown`

## 20. Audit log CSV export — New v1.1
**As** Meera, **I want** to export the audit log as CSV **so that** I can hand evidence to auditors.
- Only Compliance Officer and Platform Admin; the export itself is audited.
Test: `test_audit_csv_export_rbac`

---

## Candidate next features (not built)
Approval SLA and escalation, segregation of duties (requester cannot self-approve Finance), Teams/email notifications, Entra ID SSO, persistent storage, embeddings-based discovery, agent version pinning and canary release, per-tenant budgets, OPA/Cedar policy engine.
