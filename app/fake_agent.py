"""Fake Agent: a different workload that pretends to be the Research Agent."""
import argparse

from common import ID, banner, fetch_svid, log, post

p = argparse.ArgumentParser()
p.add_argument("--insecure", action="store_true", help="Phase 1: plain HTTP, no SPIFFE")
p.add_argument("--honest", action="store_true", help="claim 'fake-agent' instead of 'research-agent'")
args = p.parse_args()

claim = "fake-agent" if args.honest else "research-agent"
banner(f"FAKE AGENT attacking the Search Tool ({'INSECURE' if args.insecure else 'SPIFFE mTLS'})", "red")
if not args.insecure:
    fetch_svid("Fake Agent", wait=False)  # it CAN get an SVID, but only its own
log(f"Sending agent_name = '{claim}'", "red", bold=True)

status, resp = post("search-tool", 8080 if args.insecure else 8443, "/search",
                    {"agent_name": claim, "query": "agent identity credentials"},
                    expect_id=None if args.insecure else ID["search-tool"])
if status == 200:
    log("RESULT: ACCEPTED. Impersonation worked, the fake agent got protected data:", "red", bold=True)
    for r in resp["results"]:
        log(f"  - {r}", "red")
else:
    log(f"RESULT: DENIED ({status}): {resp['error']}", "green", bold=True)
