"""Shared helpers: pretty logs, SPIFFE identity (Workload API + mTLS), tiny HTTP, Groq."""
import http.client
import json
import os
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TD = "spiffe://ai-governance.demo"
ID = {
    "orchestrator": f"{TD}/agent/orchestrator",
    "research": f"{TD}/agent/research",
    "fake": f"{TD}/agent/fake",
    "search-tool": f"{TD}/service/search-tool",
}
SOCKET = "/run/spire/sockets/agent.sock"
SVID_DIR = "/tmp/svid"

# ---------- pretty logs ----------
C = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35, "cyan": 36, "grey": 90}


def log(msg, color=None, bold=False):
    code = ";".join(filter(None, ["1" if bold else "", str(C[color]) if color else ""]))
    # colour each line separately: `docker compose logs` prefixes every line
    print("\n".join(f"\033[{code}m{line}\033[0m" if code else line for line in str(msg).splitlines()), flush=True)


def banner(title, color="cyan"):
    line = "=" * 64
    log(f"{line}\n  {title}\n{line}", color, bold=True)


# ---------- SPIFFE identity ----------
def fetch_svid(who, wait=True):
    """Ask the local SPIRE Agent, over the Workload API socket, 'who am I?'.

    The workload sends NO credentials. The agent asks the kernel which process is calling,
    matches its attributes (here: Unix UID) against registration entries, and hands back
    an X.509-SVID: certificate + private key + trust bundle, written to SVID_DIR.
    """
    os.makedirs(SVID_DIR, exist_ok=True)
    cmd = ["spire-agent", "api", "fetch", "x509", "-socketPath", SOCKET, "-write", SVID_DIR]
    last = None
    while True:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            break
        err = ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1]
        if not wait:
            log(f"[{who}] NO IDENTITY from Workload API: {err}", "red", bold=True)
            raise SystemExit(1)
        if err != last:  # only log when the reason changes
            log(f"[{who}] waiting for an identity from SPIRE: {err}", "grey")
            last = err
        time.sleep(3)
    fields = dict(line.split(":", 1) for line in r.stdout.splitlines() if line.startswith(("SPIFFE ID", "SVID Valid Until")))
    spiffe_id = fields["SPIFFE ID"].strip()
    log(f"[{who}] Workload API -> SVID obtained successfully", "green", bold=True)
    log(f"[{who}] {who} SPIFFE ID: {spiffe_id}", "green", bold=True)
    log(f"[{who}] SVID valid until: {fields['SVID Valid Until'].strip()}", "grey")
    return spiffe_id


def tls_context(server):
    """mTLS context built only from the SVID: present our cert, require theirs, trust only our trust domain."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False  # SPIFFE identity lives in the URI SAN, not a DNS name; we check it ourselves
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(f"{SVID_DIR}/svid.0.pem", f"{SVID_DIR}/svid.0.key")
    ctx.load_verify_locations(f"{SVID_DIR}/bundle.0.pem")
    return ctx


def peer_spiffe_id(sock):
    """The SPIFFE ID inside the peer's verified certificate (URI SAN)."""
    san = sock.getpeercert().get("subjectAltName", ())
    return next((v for k, v in san if k == "URI"), None)


# ---------- tiny JSON-over-HTTP(S) ----------
def post(host, port, path, body, expect_id=None):
    """POST JSON. With expect_id: mutual TLS using our SVID, and verify the SERVER's SPIFFE ID too."""
    if expect_id:
        conn = http.client.HTTPSConnection(host, port, context=tls_context(server=False), timeout=120)
        conn.connect()
        server_id = peer_spiffe_id(conn.sock)
        if server_id != expect_id:
            raise RuntimeError(f"server is {server_id}, expected {expect_id}")
        log(f"   mTLS ok, server proved it is {server_id}", "grey")
    else:
        conn = http.client.HTTPConnection(host, port, timeout=120)
    conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def serve(who, handle, plain_port, tls_port):
    """Run `handle(body, peer_spiffe_id)` on a plain port (Phase 1) and an mTLS port (once SPIRE gives us an SVID)."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            peer = peer_spiffe_id(self.connection) if isinstance(self.connection, ssl.SSLSocket) else None
            status, resp = handle(body, peer)
            data = json.dumps(resp).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    plain = ThreadingHTTPServer(("", plain_port), Handler)
    threading.Thread(target=plain.serve_forever, daemon=True).start()
    log(f"[{who}] INSECURE listener on :{plain_port} (trusts whatever the caller claims)", "yellow")

    fetch_svid(who)  # blocks until SPIRE is running and this workload is registered
    secure = ThreadingHTTPServer(("", tls_port), Handler)
    secure.socket = tls_context(server=True).wrap_socket(secure.socket, server_side=True)
    log(f"[{who}] mTLS listener on :{tls_port} (callers must present an SVID from {TD})", "green")
    secure.serve_forever()


# ---------- LLM ----------
def llm(prompt):
    from groq import Groq

    r = Groq().chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        messages=[{"role": "user", "content": prompt}],
    )
    return r.choices[0].message.content.strip()
