"""Local web UI: http://127.0.0.1:<port>. Listens on localhost only; nothing leaves the machine."""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import core, merge

UI = os.path.join(os.path.dirname(__file__), "ui")


def default_roots():
    home = os.path.expanduser("~")
    names = ["Documents", "Desktop", "Downloads", "Bureau", "Téléchargements"]
    roots = [os.path.join(home, n) for n in names]
    roots += [os.path.join(home, n) for n in os.listdir(home) if n.startswith("OneDrive")]
    return [r for r in roots if os.path.isdir(r)]


class State:
    def __init__(self, roots):
        self.lock = threading.Lock()
        self.roots = roots
        self.scanning = False
        self.progress = [0, 0]
        self.error = None
        self.docs, self.families, self.problems = [], [], []
        self.reports = []
        self.finished = None
        self.took = None
        self.created = set()  # copies written by "merge" this session: the only extra paths we reveal
        self.last_seen = time.time()  # last request from an open page

    def start_scan(self, roots):
        with self.lock:
            if self.scanning:
                return False
            self.scanning, self.roots, self.error, self.progress = True, roots, None, [0, 0]
        threading.Thread(target=self._scan, daemon=True).start()
        return True

    def _scan(self):
        t = time.time()
        try:
            docs, problems = core.scan(self.roots, progress=lambda n, total, _: self._tick(n, total))
            fams = core.families(docs)
            reports = [core.report(f) for f in fams]
            order = sorted(range(len(fams)), key=lambda i: -reports[i]["score"])
            with self.lock:
                self.docs, self.problems = docs, problems
                self.families = [fams[i] for i in order]
                self.reports = [reports[i] for i in order]
        except Exception as e:  # surfaced in the UI rather than killing the thread silently
            with self.lock:
                self.error = f"{type(e).__name__}: {e}"
        with self.lock:
            self.scanning, self.finished, self.took = False, time.time(), round(time.time() - t, 1)

    def _tick(self, n, total):
        self.progress = [n, total]

    def summary(self):
        with self.lock:
            return {
                "roots": self.roots, "scanning": self.scanning, "progress": self.progress,
                "error": self.error, "finished": self.finished, "took": self.took,
                "documents": len(self.docs), "problems": self.problems[:200],
                "families": [{"i": i, "name": r["name"], "versions": len(r["versions"]), "files": r["files"],
                              "stranded": len(r["stranded"]), "received": r["received"],
                              "latest": r["versions"][r["head"]]["time"]}
                             for i, r in enumerate(self.reports)],
            }


def make_handler(state, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self):
            # Another site in the browser must not read your documents through this server
            # (DNS rebinding): only answer requests addressed to localhost by name.
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, {"error": "forbidden host"})
                return False
            state.last_seen = time.time()
            return True

        def do_GET(self):
            if not self._guard():
                return
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                with open(os.path.join(UI, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if url.path == "/api/state":
                return self._send(200, state.summary())
            if url.path == "/api/family":
                fam = self._family(q.get("i"))
                if fam is None:
                    return self._send(404, {"error": "no such family"})
                head = int(q["head"]) if q.get("head", "").isdigit() else None
                return self._send(200, core.report(fam, head))
            if url.path == "/api/diff":
                a, b = self._doc(q.get("a")), self._doc(q.get("b"))
                if not a or not b:
                    return self._send(404, {"error": "no such document"})
                return self._send(200, {"blocks": core.diff(a, b)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._send(415, {"error": "json only"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if self.path == "/api/scan":
                roots = [os.path.normpath(r) for r in body.get("roots", []) if isinstance(r, str) and r.strip()]
                missing = [r for r in roots if not os.path.isdir(r)]
                if not roots or missing:
                    return self._send(400, {"error": "missing folder", "folders": missing})
                return self._send(200, {"started": state.start_scan(roots)})
            if self.path == "/api/reveal":
                doc = self._doc(str(body.get("id")))
                path = doc.path if doc else body.get("path")
                if not doc and path not in state.created:  # never an arbitrary path
                    return self._send(404, {"error": "no such document"})
                reveal(path)
                return self._send(200, {"ok": True})
            if self.path == "/api/merge":
                fam = self._family(str(body.get("i")))
                if fam is None:
                    return self._send(404, {"error": "no such family"})
                head_id = body.get("head")
                _, head, strays = core.analyse(fam, head_id if isinstance(head_id, int) else None)
                stranded = [s for s in strays if s["status"] == "stranded"]
                if not stranded:
                    return self._send(400, {"error": "nothing left behind"})
                try:
                    out = merge.merged_copy(head["doc"], stranded)
                except (ValueError, OSError) as e:
                    return self._send(400, {"error": str(e)})
                state.created.add(out)
                return self._send(200, {"path": out, "count": len(stranded)})
            self._send(404, {"error": "not found"})

        def _family(self, i):
            with state.lock:
                if i is not None and i.isdigit() and int(i) < len(state.families):
                    return state.families[int(i)]
            return None

        def _doc(self, i):
            with state.lock:
                if i is not None and i.isdigit() and int(i) < len(state.docs):
                    return state.docs[int(i)]
            return None

    return Handler


def reveal(path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def stop_when_idle(httpd, state, minutes):
    """An open page calls the server every minute; when none has for `minutes` (tab closed),
    stop, so a server started from a shortcut does not linger unseen."""
    def watch():
        while True:
            time.sleep(15)
            if not state.scanning and time.time() - state.last_seen > minutes * 60:
                httpd.shutdown()
                return
    threading.Thread(target=watch, daemon=True).start()


def serve(roots, port=7341, open_browser=True, scan_now=True, idle_minutes=None):
    state = State(roots)
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(state, p))
            break
        except OSError:
            continue
    else:
        raise SystemExit(f"no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{p}/"
    print(f"Gleaner is open at {url}  (Ctrl+C to stop)")
    if scan_now and roots:
        state.start_scan(roots)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    if idle_minutes:
        stop_when_idle(httpd, state, idle_minutes)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
