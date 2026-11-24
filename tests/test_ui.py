"""Clicks through the real page in Chrome. Skipped when Playwright or Chrome is not installed."""
import os
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from gleaner import server
from test_core import P, story  # noqa: F401  (fixture)

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def page(story, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "reveal", lambda path: None)
    state = server.State([str(story)])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = server.make_handler(state, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state.start_scan([str(story)])
    while state.scanning or not state.finished:
        time.sleep(0.05)
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            pytest.skip("Chrome not available")
        pg = browser.new_page(locale="en-US")
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://127.0.0.1:{port}/")
        yield pg, story
        assert errors == [], errors
        browser.close()
    httpd.shutdown()


def test_open_a_document_see_the_left_behind_passage_and_merge_it(page):
    pg, story = page
    pg.get_by_role("button", name="report_final.docx").click()
    pg.get_by_text(P).wait_for()
    assert pg.locator(".row").count() == 4
    pg.get_by_role("button", name="Create a merged copy").click()
    note = pg.locator(".ok-note")
    note.wait_for()
    assert "(gleaned).docx" in note.inner_text()
    assert os.path.exists(os.path.join(story, "report_final (gleaned).docx"))


def test_click_a_version_to_compare_it_with_its_parent(page):
    pg, _ = page
    pg.get_by_role("button", name="report_final.docx").click()
    pg.locator(".row").first.wait_for()
    pg.locator(".row[data-n='0']").click()  # the original has no parent: same text
    pg.get_by_text("These two versions have the same text.").wait_for()
    pg.locator(".row[data-n='2']").click()  # v3 against v1: edits shown word by word
    pg.locator(".diff ins").first.wait_for()


def test_filter_and_deep_link(page):
    pg, _ = page
    pg.locator("#filter").fill("nothing like this")
    assert pg.locator(".list button").count() == 0
    pg.locator("#filter").fill("report")
    assert pg.locator(".list button").count() == 1
    pg.goto(pg.url.split("#")[0] + "#f=0")
    pg.reload()
    pg.get_by_text(P).wait_for()
