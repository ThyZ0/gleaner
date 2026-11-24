"""The local web server: answers only to localhost names, reads only scanned files, writes only new copies."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gleaner import core, server
from test_core import story  # noqa: F401  (fixture)


@pytest.fixture
def app(story, monkeypatch):  # noqa: F811
    revealed = []
    monkeypatch.setattr(server, "reveal", revealed.append)
    state = server.State([str(story)])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = server.make_handler(state, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state.start_scan([str(story)])
    for _ in range(100):
        if not state.scanning and state.finished:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", state, revealed
    httpd.shutdown()


def call(url, body=None, host=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_state_and_family(app):
    url, state, _ = app
    code, s = call(url + "/api/state")
    assert code == 200 and s["documents"] == 6 and len(s["families"]) == 1
    code, fam = call(url + "/api/family?i=0")
    assert code == 200 and len(fam["stranded"]) == 1 and fam["mergeable"]


def test_other_host_names_are_refused(app):
    url, _, _ = app
    code, _ = call(url + "/api/state", host="evil.example:80")
    assert code == 403


def test_reveal_only_scanned_or_created_files(app):
    url, state, revealed = app
    assert call(url + "/api/reveal", {"path": r"C:\Windows\System32\calc.exe"})[0] == 404
    assert call(url + "/api/reveal", {"id": 0})[0] == 200
    assert revealed == [state.docs[0].path]


def test_merge_writes_a_new_file_and_can_reveal_it(app):
    url, state, revealed = app
    code, r = call(url + "/api/merge", {"i": 0})
    assert code == 200 and r["count"] == 1 and r["path"].endswith("(gleaned).docx")
    assert call(url + "/api/reveal", {"path": r["path"]})[0] == 200
    assert revealed[-1] == r["path"]


def test_scan_rejects_missing_folders(app):
    url, _, _ = app
    code, r = call(url + "/api/scan", {"roots": [r"Z:\definitely\not\here"]})
    assert code == 400 and r["folders"]
