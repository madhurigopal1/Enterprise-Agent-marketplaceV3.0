"""Deterministic demo 'skills' executed by the simulated agents.

These are lightweight rule-based analyses so the POC produces meaningful, testable output
without calling any LLM. In production, each provider adapter would invoke the real agent.
"""
import re
from collections import Counter

AMBIGUOUS = ["fast", "quick", "quickly", "user-friendly", "user friendly", "easy", "easily", "simple", "flexible", "robust",
             "efficient", "efficiently", "appropriate", "as needed", "etc", "tbd", "and/or", "minimal", "adequate",
             "seamless", "intuitive", "scalable", "reasonable", "several", "some", "many", "optimal", "modern", "as appropriate"]
REQ_VERBS = re.compile(r"\b(shall|must|should|will|needs? to|has to|can|able to)\b", re.I)
MEASURE = re.compile(r"\b\d+(\.\d+)?\s?(ms|milliseconds?|seconds?|secs?|s|%|minutes?|mins?|hours?|days?|users?|requests?|tps|rps|mb|gb|records?|times|retries|attempts)\b", re.I)


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip(" -*•\t") for p in parts if len(p.strip()) > 3]


def req_sentences(text):
    return [s for s in sentences(text) if REQ_VERBS.search(s)]


def _amb(sentence):
    low = sentence.lower()
    return [w for w in AMBIGUOUS if re.search(r"\b" + re.escape(w) + r"\b", low)]


def requirement_quality(text, up, agent):
    reqs = req_sentences(text)
    findings, amb_total = [], 0
    for s in reqs:
        a = _amb(s)
        if a:
            amb_total += len(a)
            findings.append({"severity": "medium", "issue": f"Ambiguous term(s) {a}", "evidence": s[:140]})
    low = (text or "").lower()
    has_measure = bool(MEASURE.search(text or ""))
    has_err = bool(re.search(r"error|fail|exception|invalid|reject|timeout", low))
    has_ac = bool(re.search(r"acceptance|given .* when|when .* then|criteria", low))
    has_nfr = bool(re.search(r"performance|security|availability|latency|throughput|audit|compliance", low))
    score = 100 - min(30, 5 * amb_total)
    if not reqs:
        score -= 25; findings.append({"severity": "high", "issue": "No requirement statements (shall/must/should) found", "evidence": ""})
    if not has_measure:
        score -= 20; findings.append({"severity": "high", "issue": "No measurable criteria (numbers/units) found", "evidence": ""})
    if not has_err:
        score -= 10; findings.append({"severity": "medium", "issue": "No error / exception handling described", "evidence": ""})
    if not has_ac:
        score -= 10; findings.append({"severity": "medium", "issue": "No acceptance criteria stated", "evidence": ""})
    if not has_nfr:
        score -= 10; findings.append({"severity": "low", "issue": "No non-functional requirements (performance, security, audit)", "evidence": ""})
    score = max(0, score)
    verdict = "Ready" if score >= 80 else "Needs refinement" if score >= 55 else "Not ready"
    recs = []
    if amb_total: recs.append("Replace vague terms with measurable thresholds.")
    if not has_measure: recs.append("Add quantified targets (e.g. response time < 2 s, 99.5% availability).")
    if not has_ac: recs.append("Add Given/When/Then acceptance criteria per requirement.")
    if not has_err: recs.append("Specify behaviour for invalid input and failure scenarios.")
    return {"summary": f"Quality score {score}/100 across {len(reqs)} requirement statement(s): {verdict}.",
            "verdict": verdict, "score": score, "findings": findings, "recommendations": recs,
            "data": {"requirements_found": len(reqs), "ambiguous_terms": amb_total}}


def testability(text, up, agent):
    reqs = req_sentences(text)
    concrete = re.compile(r"\b(write|written|store|log|display|show|send|email|encrypt\w*|reject|retry|return|validate|redirect|notify|record)\b", re.I)
    testable = [s for s in reqs if (MEASURE.search(s) or concrete.search(s)) and not _amb(s)]
    untestable = [s for s in reqs if s not in testable]
    pct = round(100 * len(testable) / len(reqs)) if reqs else 0
    cases = [f"Verify: {s[:110]}" for s in (testable or reqs)[:6]]
    findings = [{"severity": "medium", "issue": "Not objectively testable", "evidence": s[:120]} for s in untestable[:5]]
    verdict = "Ready" if pct >= 70 else "Needs refinement" if pct >= 40 else "Not ready"
    return {"summary": f"{len(testable)} of {len(reqs)} requirement(s) are objectively testable ({pct}%).",
            "verdict": verdict, "score": pct, "findings": findings,
            "recommendations": ["Rewrite untestable statements with measurable pass/fail conditions."] if untestable else [],
            "data": {"candidate_test_cases": cases}}


def architecture(text, up, agent):
    low = (text or "").lower()
    rules = [("api|integrat|rest|service|interface", "API gateway + service layer"),
             ("database|store|persist|record|data", "Encrypted data store with backup & retention"),
             ("payment|transaction|invoice|settle", "Idempotent payment service + ledger + event bus"),
             ("real-time|notification|alert|event", "Event-driven messaging (pub/sub)"),
             ("mobile|portal|web|ui|screen|dashboard", "Responsive web/mobile front end with BFF"),
             ("report|analytics|insight", "Analytics store + BI dashboards"),
             ("login|auth|sso|user|role", "OIDC SSO with RBAC/ABAC"),
             ("ml |ai |model|predict|recommend", "Model serving with monitoring & drift detection")]
    comps = [c for pat, c in rules if re.search(pat, low)] or ["Modular monolith with API layer"]
    risks = []
    if "payment" in low: risks.append("Payment consistency & reconciliation")
    if re.search(r"third.party|external|integrat", low): risks.append("Third-party integration availability and contracts")
    if re.search(r"\d+\s?(users|tps|rps)", low): risks.append("Scalability targets require load-test validation")
    if not risks: risks.append("No major architectural risks identified from the text provided")
    return {"summary": f"Proposed {len(comps)} architectural component(s); {len(risks)} risk(s) noted.",
            "verdict": "Feasible", "findings": [{"severity": "info", "issue": r, "evidence": ""} for r in risks],
            "recommendations": comps, "data": {"components": comps, "risks": risks}}


def security_compliance(text, up, agent):
    low = (text or "").lower()
    controls, regs = [], []
    if re.search(r"personal|customer data|pii|email|phone|address|aadhaar|ssn|name", low):
        regs += ["GDPR / DPDP Act"]; controls += ["Data minimisation, masking and consent tracking"]
    if re.search(r"payment|card|pan\b|transaction", low):
        regs += ["PCI DSS"]; controls += ["Tokenise card data; segregate payment network"]
    if re.search(r"health|patient|medical", low):
        regs += ["HIPAA"]; controls += ["PHI encryption and access logging"]
    if re.search(r"login|auth|password|user", low):
        controls += ["MFA and session management"]
    if "encrypt" not in low: controls += ["Encryption in transit and at rest (not mentioned in requirements)"]
    if not re.search(r"audit|log", low): controls += ["Audit logging (not mentioned in requirements)"]
    risk = "High" if len(regs) >= 2 else "Medium" if regs else "Low"
    return {"summary": f"Security risk rating {risk}; {len(regs)} regulatory regime(s) in scope.",
            "verdict": f"{risk} risk", "findings": [{"severity": "info", "issue": f"Regulation in scope: {r}", "evidence": ""} for r in regs],
            "recommendations": controls, "data": {"regulations": regs, "risk": risk}}


def estimation(text, up, agent):
    low = (text or "").lower()
    n = max(1, len(req_sentences(text)))
    flags = sum(bool(re.search(p, low)) for p in ("integrat|api", "payment", "report|dashboard", "ml |ai |model", "migrat", "mobile"))
    lo = n * 2 + flags * 5
    hi = round(lo * 1.6)
    team = max(2, min(8, round(hi / 25)))
    return {"summary": f"Indicative effort {lo}-{hi} person-days; suggested team of {team}.", "verdict": "Estimated",
            "findings": [], "recommendations": ["Treat as a ±40% planning estimate; refine after discovery."],
            "data": {"person_days_low": lo, "person_days_high": hi, "team_size": team, "complexity_flags": flags}}


def documentation(text, up, agent):
    lines = ["# Consolidated Readiness Report", ""]
    for aid, out in up.items():
        lines += [f"## {out.get('_agent_name', aid)}", out.get("summary", ""), ""]
        for r in (out.get("recommendations") or [])[:3]:
            lines.append(f"- {r}")
        lines.append("")
    return {"summary": f"Compiled consolidated document from {len(up)} upstream agent output(s).", "verdict": "Generated",
            "findings": [], "recommendations": [], "data": {"markdown": "\n".join(lines)}}


def financial_analysis(text, up, agent):
    amounts = re.findall(r"(?:₹|\$|£|€|INR|USD|Rs\.?)\s?[\d,]+(?:\.\d+)?", text or "")
    ledger = {"budget": 1_200_000, "actual": 1_345_000}
    var = round(100 * (ledger["actual"] - ledger["budget"]) / ledger["budget"], 1)
    return {"summary": f"Synthetic ledger shows {var}% overspend vs budget; {len(amounts)} figure(s) detected in input.",
            "verdict": "Variance flagged" if var > 5 else "Within tolerance",
            "findings": [{"severity": "medium", "issue": f"Actual spend exceeds budget by {var}%", "evidence": "synthetic finance-ledger"}],
            "recommendations": ["Review top three cost centres driving variance."], "data": {"ledger_synthetic": ledger, "amounts_in_input": amounts[:10]}}


def payment_analysis(text, up, agent):
    tx = [1200, 1350, 1100, 1280, 48000, 1190, 1310, 1250]
    mean = sum(tx) / len(tx)
    sd = (sum((x - mean) ** 2 for x in tx) / len(tx)) ** 0.5
    out = [x for x in tx if abs(x - mean) > 2 * sd]
    return {"summary": f"{len(out)} anomalous transaction(s) among {len(tx)} synthetic records.",
            "verdict": "Anomalies found" if out else "Clean",
            "findings": [{"severity": "high", "issue": f"Outlier amount {x}", "evidence": "synthetic payments-db"} for x in out],
            "recommendations": ["Hold outlier settlements for manual review."], "data": {"outliers": out}}


def kyc(text, up, agent):
    low = (text or "").lower()
    items = {"Full name": r"name", "Date of birth": r"dob|date of birth|born", "Address proof": r"address",
             "Government ID": r"passport|aadhaar|pan\b|driving|national id", "Source of funds": r"source of (funds|wealth)"}
    status = {k: bool(re.search(v, low)) for k, v in items.items()}
    missing = [k for k, v in status.items() if not v]
    return {"summary": f"{len(items) - len(missing)}/{len(items)} KYC evidence items present.",
            "verdict": "Complete" if not missing else "Incomplete",
            "findings": [{"severity": "high", "issue": f"Missing: {m}", "evidence": ""} for m in missing],
            "recommendations": ["Request missing evidence before approval."] if missing else [], "data": {"checklist": status}}


def document_analysis(text, up, agent):
    sents = sentences(text)
    words = [w for w in re.findall(r"[a-zA-Z]{5,}", (text or "").lower())]
    stop = {"shall", "should", "which", "their", "there", "about", "would", "these", "those", "system", "users"}
    top = [w for w, _ in Counter(w for w in words if w not in stop).most_common(6)]
    nums = re.findall(r"\d+(?:\.\d+)?\s?%?", text or "")[:8]
    return {"summary": " ".join(sents[:2])[:260] or "No content supplied.", "verdict": "Analyzed", "findings": [],
            "recommendations": [], "data": {"top_terms": top, "key_numbers": nums, "sentence_count": len(sents)}}


KB = [("Requirements standard", "Every requirement must be atomic, testable and traceable with measurable acceptance criteria."),
      ("Security baseline", "All services must use SSO, encrypt data in transit and at rest, and log security events."),
      ("API guideline", "APIs follow semantic versioning, OAuth2 and publish OpenAPI contracts."),
      ("Data classification policy", "Classify data as Public, Internal, Confidential or Restricted and apply matching controls."),
      ("AI governance policy", "Production AI agents need an owner, security review, evaluation evidence and human approval for consequential actions."),
      ("Release policy", "Production releases require passing automated tests and an approved change record.")]


def knowledge_retrieval(text, up, agent):
    q = set(re.findall(r"[a-z]{4,}", (text or "").lower()))
    ranked = sorted(((len(q & set(re.findall(r"[a-z]{4,}", (t + " " + b).lower()))), t, b) for t, b in KB), reverse=True)
    hits = [(t, b) for s, t, b in ranked if s > 0][:3] or [KB[0]]
    return {"summary": f"Retrieved {len(hits)} relevant guidance item(s).", "verdict": "Retrieved", "findings": [],
            "recommendations": [f"{t}: {b}" for t, b in hits], "data": {"sources": [t for t, _ in hits]}}


def code_review(text, up, agent):
    pats = [(r"eval\(|exec\(", "Dynamic code execution"), (r"password\s*=|secret\s*=|api[_-]?key\s*=", "Hard-coded secret"),
            (r"select \*", "SELECT * usage"), (r"except\s*:", "Bare except"), (r"todo|fixme", "Unresolved TODO/FIXME")]
    found = [d for p, d in pats if re.search(p, text or "", re.I)]
    return {"summary": f"{len(found)} risky pattern(s) detected.", "verdict": "Issues found" if found else "Clean",
            "findings": [{"severity": "medium", "issue": d, "evidence": ""} for d in found], "recommendations": [], "data": {}}


def generic(text, up, agent):
    s = sentences(text)
    return {"summary": f"{agent['name']} processed {len(s)} statement(s) of input (generic handler).", "verdict": "Processed",
            "findings": [], "recommendations": [], "data": {}}


SKILLS = {f.__name__: f for f in (requirement_quality, testability, architecture, security_compliance, estimation, documentation,
                                  financial_analysis, payment_analysis, kyc, document_analysis, knowledge_retrieval, code_review, generic)}
