"""Agent Abstraction Layer: one normalized contract over heterogeneous providers.

Each adapter below is a SIMULATION. Replace `_call_provider` with the real SDK/HTTP call
(Neuro SAN session, NANDA-style registry lookup, Otari endpoint, AWS Bedrock Agents, REST API).
The platform only depends on the normalized response contract.
"""
import random, time, uuid
from .skills import SKILLS


class BaseAdapter:
    provider = "base"
    invoke_style = "REST"

    def session(self, agent):
        return f"{self.provider.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"

    def _call_provider(self, agent, text, upstream):
        fn = SKILLS.get(agent["skill"], SKILLS["generic"])
        return fn(text, upstream, agent)

    def invoke(self, agent, text, upstream):
        t0 = time.perf_counter()
        out = self._call_provider(agent, text, upstream)
        out["_agent_name"] = agent["name"]
        rnd = random.Random(agent["id"] + str(len(text or "")))
        base = agent.get("avg_latency_sec") or 3.0
        simulated_latency = round(base * rnd.uniform(0.8, 1.2), 2)
        tokens_in = max(1, len(text or "") // 4)
        tokens_out = max(40, len(str(out)) // 4)
        return {"output": out, "provider": self.provider, "invoke_style": self.invoke_style, "session": self.session(agent),
                "model": agent["models"][0], "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": round(agent["cost_per_call"], 4), "simulated_latency_sec": simulated_latency,
                "wall_ms": round((time.perf_counter() - t0) * 1000, 2)}


class NeuroSanAdapter(BaseAdapter):
    provider, invoke_style = "Neuro SAN", "Agent network session (streaming chat)"


class NandaAdapter(BaseAdapter):
    provider, invoke_style = "NANDA-inspired", "Registry lookup + agent-fact resolution"


class OtariAdapter(BaseAdapter):
    provider, invoke_style = "Otari", "Otari agent endpoint"


class AwsAdapter(BaseAdapter):
    provider, invoke_style = "AWS Bedrock", "Bedrock Agents InvokeAgent"


class EnterpriseApiAdapter(BaseAdapter):
    provider, invoke_style = "Enterprise API", "REST / OpenAPI"


ADAPTERS = {a.provider: a() for a in (NeuroSanAdapter, NandaAdapter, OtariAdapter, AwsAdapter, EnterpriseApiAdapter)}


def get_adapter(provider: str):
    return ADAPTERS.get(provider) or EnterpriseApiAdapter()
