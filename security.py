"""Trust & Governance layer: simulated SSO, identity, RBAC + ABAC policy, scoped delegation.

NOTE: This is a POC simulation of enterprise SSO (OIDC-style signed token). Replace with
Entra ID / Okta / Cognito in a real deployment.
"""
import base64, hashlib, hmac, json, os, time
from typing import Optional

SECRET = os.getenv("POC_SECRET", "poc-demo-secret-change-me").encode("utf-8")
CLASSIFICATION = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}
SERVING_STATUSES = {"Certified", "Production"}

GENERAL_RESOURCES = ["knowledge-base", "policy-library", "repo", "docs"]

USERS = {
    "priya": {"id": "priya", "name": "Priya Nair", "role": "Business Analyst", "persona": "Business user",
              "region": "India", "clearance": "Internal", "budget_usd": 3.00,
              "resources": GENERAL_RESOURCES},
    "arjun": {"id": "arjun", "name": "Arjun Mehta", "role": "Finance Manager", "persona": "Finance leader",
              "region": "India", "clearance": "Confidential", "budget_usd": 5.00,
              "resources": GENERAL_RESOURCES + ["finance-ledger", "payments-db"]},
    "meera": {"id": "meera", "name": "Meera Collins", "role": "Compliance Officer", "persona": "Risk & compliance",
              "region": "UK", "clearance": "Confidential", "budget_usd": 5.00,
              "resources": GENERAL_RESOURCES + ["kyc-db", "finance-ledger"]},
    "kiran": {"id": "kiran", "name": "Kiran Rao", "role": "Agent Owner", "persona": "Agent developer",
              "region": "India", "clearance": "Internal", "budget_usd": 3.00,
              "resources": GENERAL_RESOURCES},
    "sam": {"id": "sam", "name": "Sam Carter", "role": "Platform Admin", "persona": "Platform administrator",
            "region": "US", "clearance": "Restricted", "budget_usd": 10.00,
            "resources": GENERAL_RESOURCES + ["finance-ledger", "payments-db", "kyc-db", "cloud-billing"]},
}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user_id: str, ttl: int = 8 * 3600) -> str:
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + ttl, "iss": "poc-sso", "amr": ["pwd", "mfa"]}).encode())
    sig = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        claims = json.loads(_unb64(payload))
        if claims["exp"] < time.time() or claims["sub"] not in USERS:
            return None
        return USERS[claims["sub"]]
    except Exception:
        return None


def evaluate(user: dict, agent: dict, spent_usd: float = 0.0, action: str = "invoke") -> dict:
    """Zero-trust evaluation: authenticate -> RBAC -> ABAC -> validate agent -> resources -> budget."""
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    add("Authenticate", True, f"Verified SSO identity '{user['id']}' (MFA)")
    roles = agent["allowed_roles"]
    add("RBAC role", "*" in roles or user["role"] in roles,
        f"Role '{user['role']}' vs allowed {'any role' if '*' in roles else roles}")
    add("ABAC region", not agent["regions"] or user["region"] in agent["regions"] or "All" in agent["regions"],
        f"Region '{user['region']}' vs agent regions {agent['regions']}")
    need = agent["data_classification"]
    add("ABAC data classification", CLASSIFICATION[user["clearance"]] >= CLASSIFICATION[need],
        f"User clearance '{user['clearance']}' vs data classification '{need}'")
    add("Agent lifecycle", agent["status"] in SERVING_STATUSES,
        f"Agent status '{agent['status']}' (must be Certified or Production)")
    add("Kill switch", not agent.get("suspended"),
        "Agent is active" if not agent.get("suspended") else f"Agent suspended by Platform Admin: {agent.get('suspended_reason') or 'no reason given'}")
    missing = [r for r in agent["required_resources"] if r not in user["resources"]]
    add("Resource access", not missing,
        "All required resources granted" if not missing else f"Missing grants: {missing}")
    remaining = user["budget_usd"] - spent_usd
    add("Budget / quota", remaining >= agent["cost_per_call"],
        f"Remaining ${remaining:.2f} vs call cost ${agent['cost_per_call']:.2f}")
    allowed = all(c["passed"] for c in checks)
    first_fail = next((c for c in checks if not c["passed"]), None)
    return {"allowed": allowed, "checks": checks,
            "reason": None if allowed else f"{first_fail['name']}: {first_fail['detail']}"}


def delegation_for(user: dict, agent: dict, run_id: str) -> dict:
    """Scoped delegation: the agent receives ONLY its declared resource scopes - never the user's full permissions."""
    return {"subject": user["id"], "actor": agent["id"], "run_id": run_id,
            "scopes": [f"read:{r}" for r in agent["required_resources"]],
            "inherits_user_permissions": False, "inherits_upstream_agent_permissions": False}


APPROVER_ROLES = {"Platform Admin", "Compliance Officer"}


def can_approve(user: dict, run: dict) -> bool:
    """Requester may approve own run; Platform Admin and Compliance Officer may approve any run."""
    return user["id"] == run["user"] or user["role"] in APPROVER_ROLES
