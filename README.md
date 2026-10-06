# Agent Identity Governance with SPIFFE/SPIRE

---

## 0. What we built (show this first)

```
                         trust domain: ai-governance.demo
 ┌──────────────┐  task  ┌────────────────┐ search ┌────────────────────┐
 │ Orchestrator │ ─────► │ Research Agent │ ─────► │ Search Tool        │
 │ (LangGraph + │        │ (Groq summary) │        │ (PROTECTED service)│
 │  Groq)       │        └────────────────┘        └────────────────────┘
 │ uid 1001     │           uid 1002                  uid 1003      ▲
 └──────────────┘                                                   │ "I am research-agent!"
                                                    ┌───────────────┴┐
 ┌──────────────┐        ┌──────────────┐           │ Fake Agent     │
 │ SPIRE Server │◄──────►│ SPIRE Agent  │           │ uid 1004       │
 │ (authority)  │  node  │ Workload API │◄── every container asks "who am I?" over a socket
 └──────────────┘  att.  └──────────────┘
```

| File | Role |
|---|---|
| [app/orchestrator.py](app/orchestrator.py) | LangGraph: `plan → research → answer`. Delegates to the Research Agent. |
| [app/research_agent.py](app/research_agent.py) | Receives tasks, calls the Search Tool, summarises with Groq. |
| [app/search_tool.py](app/search_tool.py) | **The protected service.** All the identity decisions are made here. |
| [app/fake_agent.py](app/fake_agent.py) | The attacker. |
| [app/common.py](app/common.py) | Workload API fetch, mTLS, reading the peer's SPIFFE ID, Groq call. |
| [spire/server.conf](spire/server.conf), [spire/agent.conf](spire/agent.conf) | SPIRE configuration (about 25 lines each). |
| [spire_setup.py](spire_setup.py) | Runs the SPIRE steps and **prints every real command** before running it. |
| [docker-compose.yml](docker-compose.yml) | One container per workload. |

**One deliberate design choice to point out right away.** Every agent is a **separate container (process)**.
SPIFFE/SPIRE identifies **workloads**: processes the operating system can tell apart.
If all three LangGraph agents ran as nodes inside **one** Python process, SPIRE would see **one** workload and issue **one** identity. It cannot tell "the planner node" from "the research node". So every agent that needs its own verifiable identity has to run as its own workload. (More on this in [Workload vs. logical agent identity](#workload-identity-vs-logical-agent-identity).)

All four app containers run **the same image and the same code**. The only difference between them is *how they run* (their Unix UID). That is the point: identity comes from **attestation**, not from anything the code says about itself.

### Before class

- Docker Desktop running, Python 3 on the host, and `GROQ_API_KEY=...` in `.env`.
- Open **two terminals** in this folder:
  - **Terminal A (the "security camera"):** shows the protected service's view.
  - **Terminal B (the "stage"):** where you run the agents.
- Optional: `GROQ_MODEL` in `.env` (default `openai/gpt-oss-20b`).
- Clean start: `python spire_setup.py reset`

---

## Stage 1: The problem (no SPIFFE/SPIRE)

**Theory.** Today most agent-to-tool calls identify the caller with something the **caller supplies**: a name field, a header, or a shared API key. The service then trusts *a claim*. A claim is just bytes, and any process that can reach the service can send the same bytes.

**What we demonstrate.** Start the agent system. SPIRE is **not running yet**.

1.  Builds the app image and starts the protected Search Tool and the Research Agent in the background and  shows both services' logs live, so you can watch every request they receive and whether it's accepted or denied.

```bash
docker compose up -d --build search-tool research-agent      # Terminal B
docker compose logs -f search-tool research-agent            # Terminal A, keep it open
```

Run the real flow (User → Orchestrator → Research Agent → Search Tool):

2. Runs the real agent chain once without identity checks. The Orchestrator hands the question to the Research Agent, which calls the Search Tool, and the container is deleted when it finishes.

```bash
docker compose run --rm orchestrator --insecure "Why do AI agents need verifiable identities?"
```

Now run the attacker. It sends exactly what the real agent sends: `agent_name = "research-agent"`.
3. Runs the attacker once. It calls the Search Tool claiming to be research-agent, and the Search Tool lets it in because it only checks the name.

```bash
docker compose run --rm fake-agent --insecure
```

**What we observe.** In Terminal A, the two requests look **identical**

---

## Stage 2: Theory, just enough SPIFFE/SPIRE

The idea in one sentence: **don't ask the workload who it is. Have a trusted third party observe it, then hand it a short-lived cryptographic credential.**

| Concept | One-line meaning | In *this* project |
|---|---|---|
| **Workload** | A running piece of software (process/container) that needs an identity | Each of our 4 containers |
| **Trust domain** | The identity namespace / authority boundary | `ai-governance.demo` |
| **SPIFFE ID** | A URI naming a workload | `spiffe://ai-governance.demo/agent/research` |
| **SVID** | SPIFFE Verifiable Identity Document: a **cryptographic proof** of a SPIFFE ID. Here an X.509 certificate + private key, with the SPIFFE ID in the certificate's URI SAN | `/tmp/svid/svid.0.pem` inside each container |
| **SPIRE Server** | The identity authority. Holds the CA and the registration entries, signs SVIDs | `spire-server` container |
| **SPIRE Agent** | Runs on each node, attests local workloads, and hands them their SVIDs | `spire-agent` container |
| **Workload API** | A local Unix socket where a workload asks "who am I?". It sends **no password and no secret** | `/run/spire/sockets/agent.sock` |
| **Node attestation** | How the *agent* proves which machine it runs on | one-time **join token** |
| **Workload attestation** | How the agent works out *which workload* is calling: it asks the **kernel**, not the caller | `unix` attestor: kernel-reported **UID** |
| **Registration entry** | The rule "a workload with these properties (selectors) gets this SPIFFE ID" | `unix:uid:1002 → …/agent/research` |


---

## Stage 3: Give agents/workloads identities

**Theory.** Identity issuance has two layers. First the **node** (SPIRE Agent) proves itself to the Server. Then the Agent **attests each workload** locally and issues an SVID only if a registration entry matches.

**What I demonstrate.**

**Step 3a: start the identity authority and attest the node.**

```bash
python spire_setup.py start
```

The script prints each real command as it runs it:

1. `docker compose up -d spire-server`: the authority for `ai-governance.demo` comes up.
2. `spire-server token generate -spiffeID spiffe://ai-governance.demo/node/classroom-host`: a one-time token.
3. The `spire-agent` starts with that token, and `spire-server agent list` shows:
   `SPIFFE ID : spiffe://ai-governance.demo/spire/agent/join_token/…   Attestation type : join_token`

**Step 3b: show that running is not the same as having an identity.** Look at Terminal A. The services are now reaching the agent, but:

```
[Search Tool] waiting for an identity from SPIRE: rpc error: code = PermissionDenied desc = no identity issued
```

Run the fake agent in secure mode:

```bash
docker compose run --rm fake-agent
# [Fake Agent] NO IDENTITY from Workload API: ... no identity issued
```

**Step 3c: register workloads.** This is the governance decision: *who gets which identity*.

```bash
python spire_setup.py register
```

`python spire_setup.py register` tells the **SPIRE Server** which identity each container should get.

It creates **four registration rules**, one for each container.

Each rule basically says:

> **"The container running as this user ID gets this SPIFFE ID."**

| Runs as User ID | Gets Identity |
|---|---|
| `1001` | `spiffe://ai-governance.demo/agent/orchestrator` |
| `1002` | `spiffe://ai-governance.demo/agent/research` |
| `1003` | `spiffe://ai-governance.demo/service/search-tool` |
| `1004` | `spiffe://ai-governance.demo/agent/fake` |

(Yes, the fake agent gets a *real* identity: its own. That is realistic. Attackers are often legitimate workloads that misbehave.)

See the logs on docker you will see somthing like this

```bash
[Research Agent] Workload API -> SVID obtained successfully

[Research Agent] Research Agent SPIFFE ID: spiffe://ai-governance.demo/agent/research

[Research Agent] SVID valid until: 2026-10-04 07:54:14 +0000 UTC

[Research Agent] mTLS listener on :9443 (callers must present an SVID from spiffe://ai-governance.demo)
```


---

## Stage 4: Verify agent identity

**Theory.** With SVIDs, agents talk over **mutual TLS (mTLS)**. Both sides present certificates, and both verify that the certificate chains to the trust-domain CA. Afterwards, the receiver can read the **verified** SPIFFE ID of the other side. The question *"which workload actually made this request?"* is answered by the TLS handshake, not by the request body.


```bash
docker compose run --rm orchestrator "Why do AI agents need verifiable identities?"
```

**What students observe.**

Terminal B (Orchestrator):
```
[Orchestrator] Workload API -> SVID obtained successfully
[Orchestrator] Orchestrator SPIFFE ID: spiffe://ai-governance.demo/agent/orchestrator
[research] delegating to Research Agent (mTLS + SVID)
   mTLS ok, server proved it is spiffe://ai-governance.demo/agent/research
```

Terminal A (Research Agent, then Search Tool):
```
Research Agent: task received (mTLS)
  Caller SPIFFE ID: spiffe://ai-governance.demo/agent/orchestrator
  -> calling Search Tool as agent_name='research-agent' (mTLS + SVID)
   mTLS ok, server proved it is spiffe://ai-governance.demo/service/search-tool

Search Tool: request on mTLS endpoint
  Claimed agent        : research-agent
  Authenticated SPIFFE : spiffe://ai-governance.demo/agent/research   (from the caller's verified SVID)
  Identity check       : claim matches SVID
  Policy check         : research identity allowed
  >>> REQUEST ACCEPTED
```


---

## Stage 5: Repeat the impersonation attack (the "aha" moment)

**Theory.** The attacker can still *type* anything into the request. What it can no longer do is **prove** the identity it types.

**What I demonstrate.** Exactly the same attack as Stage 1, minus `--insecure`:

```bash
docker compose run --rm fake-agent
```


Terminal B:
```
[Fake Agent] Fake Agent SPIFFE ID: spiffe://ai-governance.demo/agent/fake
Sending agent_name = 'research-agent'
RESULT: DENIED (403): Identity verification/mapping FAILED: 'research-agent' must be spiffe://ai-governance.demo/agent/research
```

Terminal A:
```
Search Tool: request on mTLS endpoint
  Claimed agent        : research-agent
  Authenticated SPIFFE : spiffe://ai-governance.demo/agent/fake   (from the caller's verified SVID)
  Identity verification/mapping FAILED: 'research-agent' must be spiffe://ai-governance.demo/agent/research
  >>> REQUEST DENIED
```

And the attacker can't fall back to the old plain-HTTP path either. Each service closed it the moment it got its SVID:

```bash
docker compose run --rm fake-agent --insecure
# ConnectionRefusedError: the insecure port no longer exists
```

---

## Stage 6: Simple identity-based governance

**Theory.** Two separate questions:

1. **Authentication: WHO/WHAT is calling?** → SPIFFE/SPIRE
2. **Authorization: WHAT may that verified identity do?** → a policy layer (OpenFGA, OPA, Cedar)


---

## Reset / troubleshooting

```bash
python spire_setup.py reset     # removes all containers + the socket volume; start again from Stage 1
```

