"""Discovery & Catalog layer: agent registry, lifecycle and semantic (TF-IDF) capability discovery."""
import math, re
from collections import Counter
from copy import deepcopy

LIFECYCLE = ["Experimental", "Registered", "Validated", "Certified", "Production", "Deprecated"]


def _agent(id, name, provider, skill, description, capabilities, tasks, keywords, status, stage=3,
           roles=("*",), cls="Internal", regions=("All",), resources=("knowledge-base",), approval=False,
           cost=0.02, owner="Enterprise AI CoE", tools=("REST",), models=("gpt-4o",), quality=90,
           success=97.0, latency=4.0, version="1.0"):
    return {
        "id": id, "name": name, "version": version, "provider": provider, "skill": skill,
        "description": description, "capabilities": list(capabilities), "tasks": list(tasks),
        "keywords": list(keywords), "tools": list(tools), "auth": "OAuth2 client-credentials + workload identity",
        "models": list(models), "data_classification": cls, "owner": owner,
        "sla": {"p95_sec": round(latency * 1.8, 1), "availability": "99.5%"},
        "cost_per_call": cost, "regions": list(regions), "allowed_roles": list(roles),
        "required_resources": list(resources), "requires_approval": approval, "status": status,
        "stage": stage, "quality_score": quality, "success_rate": success, "avg_latency_sec": latency,
        "identity_verified": status not in ("Experimental",), "security_review": "PASSED" if status in ("Certified", "Production") else "PENDING",
    }


SEED_AGENTS = [
    _agent("req-quality", "Requirement Quality Agent", "Neuro SAN", "requirement_quality",
           "Analyzes requirements and user stories to identify ambiguity, missing acceptance criteria, incompleteness and quality gaps.",
           ["requirement analysis", "quality gap detection", "ambiguity detection", "completeness check"],
           ["analyze requirements", "review user stories", "identify quality gaps"],
           ["requirement", "story", "ambiguity", "quality", "readiness", "backlog", "work item", "development ready"],
           "Production", stage=1, owner="SDLC AI Team", quality=94, success=98.3, latency=3.1, version="3.2", cost=0.02),
    _agent("testability", "Testability Agent", "Neuro SAN", "testability",
           "Assesses whether requirements are testable and drafts candidate test cases and acceptance checks.",
           ["testability assessment", "test case generation", "acceptance criteria"],
           ["assess testability", "generate test cases"], ["test", "testing", "QA", "acceptance", "verify", "coverage"],
           "Production", stage=1, owner="SDLC AI Team", quality=91, success=97.5, latency=3.6, version="2.4", cost=0.02),
    _agent("arch-review", "Architecture Review Agent", "Otari", "architecture",
           "Proposes solution components, integration patterns and architectural risks from functional needs.",
           ["architecture review", "solution design", "integration patterns", "risk identification"],
           ["review architecture", "design solution"], ["architecture", "design", "component", "integration", "pattern", "scalability"],
           "Production", stage=2, owner="Architecture CoE", quality=89, success=96.2, latency=5.4, version="1.8", cost=0.03),
    _agent("sec-compliance", "Security & Compliance Agent", "AWS Bedrock", "security_compliance",
           "Evaluates security, privacy and regulatory implications (PII, payments, health data) and recommends controls.",
           ["security assessment", "compliance mapping", "privacy impact", "threat identification"],
           ["assess security", "check compliance"], ["security", "compliance", "privacy", "PCI", "GDPR", "PII", "risk", "controls"],
           "Production", stage=3, resources=("policy-library",), owner="Security CoE", quality=92, success=98.0, latency=4.8, version="2.1", cost=0.03),
    _agent("estimation", "Estimation Agent", "Enterprise API", "estimation",
           "Estimates effort, team sizing and delivery range based on scope and complexity signals.",
           ["effort estimation", "capacity planning", "delivery range"], ["estimate effort", "size project"],
           ["estimate", "effort", "sizing", "cost", "timeline", "person days", "schedule"],
           "Production", stage=4, owner="PMO Analytics", tools=("REST", "Jira"), quality=86, success=95.1, latency=2.9, version="1.5", cost=0.01),
    _agent("doc-gen", "Documentation Agent", "NANDA-inspired", "documentation",
           "Consolidates findings from other agents into a structured readiness or decision document.",
           ["documentation generation", "report consolidation", "executive summary"], ["write summary", "consolidate report"],
           ["documentation", "document", "report", "summary", "consolidate", "write up"],
           "Production", stage=5, owner="Enterprise AI CoE", quality=90, success=98.9, latency=3.3, version="1.3", cost=0.02),
    _agent("fin-analysis", "Financial Analysis Agent", "AWS Bedrock", "financial_analysis",
           "Analyzes financial figures, variances and budget exposure; requires human approval before running.",
           ["financial analysis", "variance analysis", "budget review"], ["analyze finances", "review budget"],
           ["finance", "financial", "budget", "variance", "revenue", "profit", "spend", "ledger"],
           "Production", stage=3, roles=("Finance Manager", "Compliance Officer", "Platform Admin"), cls="Confidential",
           regions=("US", "UK", "India"), resources=("finance-ledger",), approval=True, owner="Finance AI Team",
           quality=94, success=98.3, latency=6.2, version="3.2", cost=0.12),
    _agent("payment-analysis", "Payment Analysis Agent", "AWS Bedrock", "payment_analysis",
           "Detects anomalies and unusual patterns in payment transactions for B2B flows.",
           ["payment analysis", "anomaly detection", "transaction monitoring"], ["analyze payments", "detect anomalies"],
           ["payment", "transaction", "anomaly", "fraud", "settlement", "B2B", "outlier"],
           "Certified", stage=3, roles=("Finance Manager", "Platform Admin"), cls="Confidential", regions=("India", "US"),
           resources=("payments-db",), owner="Payments Engineering", quality=88, success=96.8, latency=5.1, version="2.0", cost=0.08),
    _agent("kyc", "KYC Verification Agent", "Otari", "kyc",
           "Checks completeness of customer identity and due-diligence evidence for KYC onboarding.",
           ["kyc verification", "identity validation", "due diligence"], ["verify customer", "check onboarding"],
           ["kyc", "customer", "identity", "onboarding", "aml", "due diligence", "verification"],
           "Certified", stage=3, roles=("Compliance Officer", "Platform Admin"), cls="Confidential", regions=("UK", "India", "US"),
           resources=("kyc-db",), approval=True, owner="Risk Technology", quality=90, success=97.2, latency=5.7, version="1.9", cost=0.10),
    _agent("doc-analysis", "Document Analysis Agent", "NANDA-inspired", "document_analysis",
           "Summarizes documents and extracts key figures, entities and themes.",
           ["document analysis", "summarization", "entity extraction"], ["summarize document", "extract key facts"],
           ["document", "summarize", "extract", "contract", "pdf", "entities", "key points"],
           "Production", stage=2, owner="Enterprise AI CoE", quality=88, success=97.0, latency=4.2, version="2.2", cost=0.02),
    _agent("knowledge", "Knowledge Retrieval Agent", "Neuro SAN", "knowledge_retrieval",
           "Retrieves relevant enterprise guidance, standards and policies from the knowledge base (RAG).",
           ["knowledge retrieval", "policy lookup", "RAG search"], ["find policy", "retrieve guidance"],
           ["knowledge", "policy", "standard", "guideline", "search", "rag", "how to"],
           "Production", stage=2, owner="Knowledge Management", quality=87, success=97.9, latency=2.4, version="1.6", cost=0.01),
    _agent("code-review", "Code Review Agent", "Enterprise API", "code_review",
           "Reviews code snippets for risky patterns, secrets and maintainability issues.",
           ["code review", "static pattern check", "secret detection"], ["review code", "find code risks"],
           ["code", "review", "pull request", "bug", "secret", "refactor", "static analysis"],
           "Certified", stage=3, resources=("repo",), owner="Engineering Excellence", quality=85, success=95.5, latency=4.4, version="1.2", cost=0.02),
    _agent("cost-optimizer", "Cloud Cost Optimizer", "AWS Bedrock", "generic",
           "Finds cloud spend optimization opportunities across accounts.",
           ["cloud cost optimization", "rightsizing"], ["optimize cloud cost"], ["cloud", "cost", "finops", "rightsizing", "aws bill"],
           "Validated", stage=3, roles=("Platform Admin",), cls="Confidential", resources=("cloud-billing",),
           owner="FinOps Team", quality=78, success=92.0, latency=7.0, version="0.9", cost=0.05),
    _agent("incident-triage", "Incident Triage Agent", "Otari", "generic",
           "Classifies incidents and proposes first-response runbooks.",
           ["incident triage", "runbook suggestion"], ["triage incident"], ["incident", "outage", "alert", "runbook", "sev1", "triage"],
           "Experimental", stage=3, owner="SRE Guild", quality=70, success=88.0, latency=6.5, version="0.3", cost=0.03),
]

AGENTS = {a["id"]: deepcopy(a) for a in SEED_AGENTS}

STOP = set("a an the of to for and or in on with by is are be can it this that find me i we our my from as at into do does need want who what which how please".split())
SYNONYMS = {
    "ready for development": "requirement quality testability architecture security estimation consolidate report summary",
    "development ready": "requirement quality testability architecture security estimation consolidate report summary",
    "readiness": "requirement quality testability",
    "gaps": "quality ambiguity incomplete",
    "safe": "security compliance privacy",
    "secure": "security compliance privacy",
    "money": "finance budget financial",
    "invoice": "payment transaction finance",
    "onboard": "kyc customer identity verification",
    "bug": "code review defect",
    "how long": "estimate effort timeline",
    "cost": "estimate effort budget",
}


def tok(text: str):
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-/]*", text.lower()):
        if w in STOP:
            continue
        for suf in ("ing", "ies", "es", "ed", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.append(w)
    return out


def _doc_tokens(a):
    toks = []
    toks += tok(a["name"]) * 2
    toks += tok(a["description"])
    for c in a["capabilities"]:
        toks += tok(c) * 3
    for t in a["tasks"]:
        toks += tok(t) * 2
    for k in a["keywords"]:
        toks += tok(k) * 3
    return toks


def discover(query: str, include_all: bool = True):
    """Intent-based semantic ranking: synonym expansion + TF-IDF cosine over agent metadata."""
    q = query.lower()
    expanded = query
    for phrase, extra in SYNONYMS.items():
        if phrase in q:
            expanded += " " + extra
    qt = tok(expanded)
    if not qt:
        return []
    docs = {aid: Counter(_doc_tokens(a)) for aid, a in AGENTS.items()}
    n = len(docs)
    df = Counter()
    for c in docs.values():
        df.update(set(c))
    idf = {t: math.log((1 + n) / (1 + df[t])) + 1 for t in df}
    qv = Counter(qt)
    qvec = {t: (1 + math.log(c)) * idf.get(t, 0) for t, c in qv.items() if t in idf}
    qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1
    res = []
    for aid, c in docs.items():
        dvec = {t: (1 + math.log(v)) * idf[t] for t, v in c.items()}
        dnorm = math.sqrt(sum(v * v for v in dvec.values())) or 1
        dot = sum(qvec[t] * dvec.get(t, 0) for t in qvec)
        score = dot / (qnorm * dnorm)
        matched = sorted({t for t in qvec if t in dvec})
        if score > 0:
            res.append({"agent_id": aid, "score": round(min(score * 2.2, 1.0), 3), "matched_terms": matched[:8]})
    res.sort(key=lambda r: -r["score"])
    return res


def validate_registration(d: dict):
    errs = []
    for f in ("id", "name", "provider", "description", "owner"):
        if not str(d.get(f, "")).strip():
            errs.append(f"'{f}' is required")
    if d.get("id") and not re.fullmatch(r"[a-z0-9][a-z0-9\-]{2,40}", d["id"]):
        errs.append("'id' must be 3-41 chars of lowercase letters, digits, hyphens")
    if d.get("id") in AGENTS:
        errs.append(f"agent id '{d['id']}' already exists")
    if not d.get("capabilities"):
        errs.append("at least one capability is required")
    if d.get("data_classification") not in ("Public", "Internal", "Confidential", "Restricted"):
        errs.append("'data_classification' must be Public|Internal|Confidential|Restricted")
    return errs


def register(d: dict):
    a = _agent(d["id"], d["name"], d["provider"], "generic", d["description"], d["capabilities"],
               d.get("tasks") or [], d.get("keywords") or [], "Registered", stage=3,
               roles=d.get("allowed_roles") or ("*",), cls=d["data_classification"],
               regions=d.get("regions") or ("All",), resources=d.get("required_resources") or ("knowledge-base",),
               approval=bool(d.get("requires_approval")), cost=float(d.get("cost_per_call", 0.02)),
               owner=d["owner"], tools=d.get("tools") or ("REST",), models=d.get("models") or ("gpt-4o",),
               quality=0, success=0.0, latency=0.0, version=d.get("version", "0.1"))
    a["quality_score"] = None
    a["success_rate"] = None
    a["avg_latency_sec"] = None
    AGENTS[a["id"]] = a
    return a


def promote(agent_id: str, target: str):
    a = AGENTS[agent_id]
    cur, tgt = LIFECYCLE.index(a["status"]), LIFECYCLE.index(target)
    if target != "Deprecated" and tgt != cur + 1:
        raise ValueError(f"Invalid transition {a['status']} -> {target}; lifecycle must advance one step at a time")
    a["status"] = target
    if target in ("Certified", "Production"):
        a["security_review"] = "PASSED"
    if target != "Experimental":
        a["identity_verified"] = True
    return a
