"""Classroom helper: every docker/SPIRE command is printed before it runs, so students see the real steps.

    python spire_setup.py start      # SPIRE Server up, node attestation of the SPIRE Agent
    python spire_setup.py register   # registration entries: "workload with UID X gets SPIFFE ID Y"
    python spire_setup.py show       # list attested agents and registration entries
    python spire_setup.py reset      # tear everything down
"""
import os
import subprocess
import sys
import time

TD = "spiffe://ai-governance.demo"
NODE = f"{TD}/node/classroom-host"
# (container, SPIFFE ID path, UID). UIDs must match `user:` in docker-compose.yml.
WORKLOADS = [
    ("orchestrator", "agent/orchestrator", 1001),
    ("research-agent", "agent/research", 1002),
    ("search-tool", "service/search-tool", 1003),
    ("fake-agent", "agent/fake", 1004),
]
SERVER = ["docker", "compose", "exec", "-T", "spire-server", "/opt/spire/bin/spire-server"]


def run(cmd, check=True, quiet=False, **kw):
    if not quiet:
        print(f"\n\033[1;36m$ {' '.join(cmd)}\033[0m", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if not quiet:
        print((r.stdout + r.stderr).strip())
    if check and r.returncode:
        sys.exit(f"command failed: {r.stderr.strip()}")
    return r


def wait_for(cmd, what):
    for _ in range(30):
        if run(cmd, check=False, quiet=True).returncode == 0:
            return
        time.sleep(2)
    sys.exit(f"timed out waiting for {what}")


def start():
    print("\n## 1. Start the SPIRE Server (identity authority for trust domain ai-governance.demo)")
    run(["docker", "compose", "up", "-d", "spire-server"])
    wait_for(SERVER + ["healthcheck"], "SPIRE Server")

    print("\n## 2. Issue a one-time join token for this node (node attestation)")
    token = run(SERVER + ["token", "generate", "-spiffeID", NODE]).stdout.split()[-1]

    print("\n## 3. Start the SPIRE Agent; it attests to the server with the token")
    run(["docker", "compose", "--profile", "agent", "up", "-d", "spire-agent"], env={**os.environ, "JOIN_TOKEN": token})
    wait_for(["docker", "compose", "exec", "-T", "spire-agent", "/opt/spire/bin/spire-agent", "healthcheck",
              "-socketPath", "/run/spire/sockets/agent.sock"], "SPIRE Agent")
    run(SERVER + ["agent", "list"])


def register():
    print("\n## 4. Registration entries: map workload attributes (selectors) -> SPIFFE ID")
    for _, path, uid in WORKLOADS:
        # check=False: re-running after entries exist just prints "similar entry already exists"
        run(SERVER + ["entry", "create", "-parentID", NODE, "-spiffeID", f"{TD}/{path}", "-selector", f"unix:uid:{uid}"],
            check=False)


def show():
    run(SERVER + ["agent", "list"], check=False)
    run(SERVER + ["entry", "show"], check=False)


def reset():
    run(["docker", "compose", "--profile", "agent", "--profile", "cli", "down", "-v", "--remove-orphans"])


if __name__ == "__main__":
    {"start": start, "register": register, "show": show, "reset": reset}[sys.argv[1] if len(sys.argv) > 1 else "start"]()
