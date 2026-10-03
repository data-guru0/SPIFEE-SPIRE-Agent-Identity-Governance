"""Protected Search Tool. The question it must answer: WHICH workload is calling me?"""
from common import ID, banner, log, serve

DOCS = [
    "EU AI Act: high-risk AI systems need logging, traceability and human oversight.",
    "NIST AI RMF: Govern, Map, Measure, Manage. Accountability requires knowing which system acted.",
    "Agent identity: every autonomous agent should have a verifiable, non-shareable identity.",
    "Least privilege: an agent should only reach the tools its task requires.",
    "Audit trails: logs must record the verified identity of the actor, not a self-declared name.",
    "Credential risk: static API keys and names in requests can be copied, leaked or spoofed.",
]

# Phase 1 "policy": a list of trusted NAMES. Anyone can type a name.
ALLOWED_NAMES = {"research-agent"}

# Phase 2: which verified workload each claimed name must actually be...
NAME_TO_ID = {"research-agent": ID["research"], "orchestrator": ID["orchestrator"], "fake-agent": ID["fake"]}
# ...and which verified identities may use this tool.
# ponytail: one-line allowlist on purpose; OpenFGA / OPA / Cedar replace this later in the course.
ALLOWED_IDS = {ID["research"]}


def search(query):
    words = set(query.lower().split())
    return sorted(DOCS, key=lambda d: -len(words & set(d.lower().replace(":", " ").replace(",", " ").split())))[:3]


def deny(reason):
    log(f"  {reason}", "red")
    log("  >>> REQUEST DENIED", "red", bold=True)
    return 403, {"error": reason}


def handle(body, peer_id):
    claimed = body.get("agent_name")
    if peer_id is None:
        banner("Search Tool: request on INSECURE endpoint", "yellow")
        log(f"  Claimed agent        : {claimed}")
        log("  Verified identity    : NONE, trusting the claim", "yellow")
        if claimed not in ALLOWED_NAMES:
            return deny(f"name '{claimed}' not in allowlist")
        log("  >>> REQUEST ACCEPTED (because the caller SAID it is research-agent)", "yellow", bold=True)
        return 200, {"results": search(body.get("query", ""))}

    banner("Search Tool: request on mTLS endpoint", "magenta")
    log(f"  Claimed agent        : {claimed}")
    log(f"  Authenticated SPIFFE : {peer_id}   (from the caller's verified SVID)", bold=True)
    # 1. Authentication: does the claim match the cryptographically proven workload?
    if NAME_TO_ID.get(claimed) != peer_id:
        return deny(f"Identity verification/mapping FAILED: '{claimed}' must be {NAME_TO_ID.get(claimed)}")
    log("  Identity check       : claim matches SVID", "green")
    # 2. Authorization (tiny): may this verified identity use the search tool?
    if peer_id not in ALLOWED_IDS:
        return deny(f"Policy: {peer_id} is not allowed to use the Search Tool")
    log("  Policy check         : research identity allowed", "green")
    log("  >>> REQUEST ACCEPTED", "green", bold=True)
    return 200, {"results": search(body.get("query", ""))}


if __name__ == "__main__":
    serve("Search Tool", handle, plain_port=8080, tls_port=8443)
