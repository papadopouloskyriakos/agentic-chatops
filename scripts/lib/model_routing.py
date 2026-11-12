#!/usr/bin/env python3
"""model_routing.py — central model-orchestration registry resolver (Plane B).

config/model-routing.json is the SINGLE SOURCE OF TRUTH for which model + provider each agentic
component uses. This resolver turns a component name into a concrete call target, so a component
reads its model from ONE place instead of a hardcoded ID. Read-only; no network.

  resolve(component[, default_model]) -> {component, provider, model, plane, api_base, auth_env, notes, fallback}
  model_for(component[, default])     -> just the model id (with a safe fallback)

For provider 'litellm', api_base/auth_env point at the shared gateway LiteLLM (LITELLM_GATEWAY_KEY)
and `model` is a gw-* model name. Plane A (the dispatched-session Anthropic<->Z.ai subscription
switch) is handled separately by scripts/claude-provider.sh + the ~/gateway.claude_provider sentinel.

CLI:  model_routing.py [--list] | --resolve <component> | --providers
"""
import os, json, argparse

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.environ.get("MODEL_ROUTING_CONFIG", os.path.join(_REPO, "config", "model-routing.json"))


def load():
    with open(REGISTRY) as f:
        return json.load(f)


def _live_dispatched_provider():
    """Plane A: the dispatched-session provider is flipped LIVE in ~/.claude/settings.json by
    claude-provider.sh (NOT this registry). Read that env block so resolve() reports the TRUTH for
    subscription-plane components instead of the static default. Returns (provider, opus_model) or None
    if undeterminable (→ fall back to the static entry). Read-only, fail-soft. IFRNLLEI01PRD-1571."""
    try:
        with open(os.path.expanduser("~/.claude/settings.json")) as f:
            env = (json.load(f).get("env") or {})
    except Exception:
        return None                                   # no/unreadable settings.json → keep the static entry
    # settings.json IS the live toggle (claude-provider.sh writes it): a z.ai base = Z.ai, otherwise
    # (no base override, or a plain Anthropic base) = the Max subscription. Either way we know the state.
    base = (env.get("ANTHROPIC_BASE_URL") or "").lower()
    if "z.ai" in base or "zai" in base:
        return "zai", env.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "glm-5.2")
    return "anthropic-max", "opus"


def resolve(component, default_model=None):
    reg = load()
    comps = reg.get("components", {})
    provs = reg.get("providers", {})
    c = comps.get(component)
    fb = False
    if c is None:
        if default_model is None:
            raise KeyError("unknown component %r (not in %s)" % (component, REGISTRY))
        c = {"provider": "anthropic-api", "model": default_model}
        fb = True
    p = provs.get(c["provider"], {})
    out = {"component": component, "provider": c["provider"], "model": c["model"],
           "plane": c.get("plane", p.get("plane", "api")),
           "api_base": p.get("api_base"), "auth_env": p.get("auth_env"),
           "notes": c.get("notes", ""), "fallback": fb, "live": False}
    # Plane A: overlay the LIVE provider toggle for subscription-plane components (dispatched-session),
    # so the resolver reflects the current claude-provider.sh switch, not just the registry default.
    if out["plane"] == "subscription":
        live = _live_dispatched_provider()
        if live:
            out["provider"], out["model"], out["live"] = live[0], live[1], True
            out["notes"] = (out["notes"] + " [LIVE toggle via claude-provider.sh]").strip()
    return out


def model_for(component, default=None):
    try:
        return resolve(component, default_model=default)["model"]
    except (KeyError, FileNotFoundError, ValueError):
        if default is not None:
            return default
        raise


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="components -> provider/model (default)")
    ap.add_argument("--resolve", metavar="COMPONENT", help="full resolved target for one component")
    ap.add_argument("--providers", action="store_true", help="list providers")
    a = ap.parse_args()
    reg = load()
    if a.resolve:
        print(json.dumps(resolve(a.resolve), indent=2))
    elif a.providers:
        for n, p in reg["providers"].items():
            print("%-16s %-13s %s" % (n, p.get("plane", "?"), p.get("api_base") or "(default)"))
    else:
        for n, c in reg["components"].items():
            print("%-22s -> %-14s %s" % (n, c["provider"], c["model"]))


if __name__ == "__main__":
    _main()
