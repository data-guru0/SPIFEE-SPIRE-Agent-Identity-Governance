"""Orchestrator Agent: a 3-node LangGraph (plan -> research -> answer). Delegates research to another workload."""
import argparse
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from common import ID, banner, fetch_svid, llm, log, post

p = argparse.ArgumentParser()
p.add_argument("question", nargs="?", default="Why do AI agents need verifiable identities?")
p.add_argument("--insecure", action="store_true", help="Phase 1: plain HTTP, no SPIFFE")
args = p.parse_args()


class State(TypedDict, total=False):
    question: str
    task: str
    findings: str
    answer: str


def plan(s):
    task = llm(f"Turn this question into a 4-8 word search query. Output only the query.\nQuestion: {s['question']}")
    log(f"[plan] research task: {task}", "cyan")
    return {"task": task}


def research(s):
    log(f"[research] delegating to Research Agent ({'plain HTTP' if args.insecure else 'mTLS + SVID'})", "cyan")
    status, resp = post(
        "research-agent", 9080 if args.insecure else 9443, "/research", {"task": s["task"]},
        expect_id=None if args.insecure else ID["research"],
    )
    if status != 200:
        raise SystemExit(f"Research Agent failed: {resp}")
    return {"findings": resp["summary"]}


def answer(s):
    return {"answer": llm(f"Answer in 4 sentences using these findings.\nQuestion: {s['question']}\nFindings:\n{s['findings']}")}


g = StateGraph(State)
g.add_node("plan", plan)
g.add_node("research", research)
g.add_node("answer", answer)
g.add_edge(START, "plan")
g.add_edge("plan", "research")
g.add_edge("research", "answer")
g.add_edge("answer", END)

banner(f"Orchestrator ({'INSECURE' if args.insecure else 'SPIFFE mTLS'})")
if not args.insecure:
    fetch_svid("Orchestrator", wait=False)
result = g.compile().invoke({"question": args.question})
banner("Final answer", "green")
log(result["answer"])
