"""Research Agent: its own container, its own SPIFFE ID. Takes tasks from the Orchestrator, calls the Search Tool."""
from common import ID, banner, llm, log, post, serve


def handle(body, peer_id):
    secure = peer_id is not None
    banner(f"Research Agent: task received ({'mTLS' if secure else 'INSECURE'})", "blue")
    if secure:
        log(f"  Caller SPIFFE ID: {peer_id}")
        if peer_id != ID["orchestrator"]:  # only the orchestrator may delegate work to me
            log("  >>> DENIED: only the orchestrator may assign research tasks", "red", bold=True)
            return 403, {"error": "only the orchestrator may assign tasks"}

    task = body["task"]
    log(f"  Task: {task}")
    log(f"  -> calling Search Tool as agent_name='research-agent' ({'mTLS + SVID' if secure else 'plain HTTP'})")
    status, resp = post(
        "search-tool", 8443 if secure else 8080, "/search",
        {"agent_name": "research-agent", "query": task},
        expect_id=ID["search-tool"] if secure else None,
    )
    if status != 200:
        log(f"  Search Tool refused: {resp}", "red")
        return status, resp

    log(f"  Search Tool returned {len(resp['results'])} results, summarising with Groq...", "green")
    summary = llm("Summarise these findings in 3 bullet points for the task "
                  f"'{task}':\n" + "\n".join(resp["results"]))
    return 200, {"summary": summary}


if __name__ == "__main__":
    serve("Research Agent", handle, plain_port=9080, tls_port=9443)
