"""The home page scan scene shows what the real detector finds, and works without its script."""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client  # noqa: E402,F401


def test_every_step_is_flagged_by_the_detector_on_its_own_phrase():
    import showcase
    showcase.scan_model.cache_clear()
    m = showcase.scan_model()
    assert [s["rule_id"] for s in m["steps"]] == list(showcase.STEP_RULES.values())    # a rule change that drops one fails here
    assert m["verdict"] == "Scam. Stop here." and m["score"] >= 65 and m["signals"] >= len(m["steps"])


def test_home_renders_the_scene_finished_so_it_reads_without_javascript(client):
    html = client.get("/").text
    scene = html[html.index('<section class="scan"'):html.index('<section class="how"')]
    assert 'class="scan live"' not in scene                                    # live mode is added by the script only
    assert "Know it's real" in scene and 'href="/login"' in scene and 'href="/check"' in scene
    assert re.search(r"\d+ approved listing|Approved listings will appear here", scene)
    for s in range(1, 7):
        assert scene.count(f'data-s="{s}"') == 2, s                            # the phrase and its flag
    assert "Payment through irreversible channels" in scene and "Scam risk 100/100" in scene
    assert "{JOIN}" not in html and "{CHECK}" not in html and "{COUNT}" not in html


def test_font_and_script_are_served_from_the_site(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "font-src 'self'" in csp and "fonts.g" not in csp
    f = client.get("/static/fonts/anton-latin.woff2")
    assert f.status_code == 200 and f.headers["content-type"] == "font/woff2" and f.content[:4] == b"wOF2"
    j = client.get("/static/scan.js")
    assert j.status_code == 200 and "javascript" in j.headers["content-type"] and "prefers-reduced-motion" in j.text


def test_signed_in_home_has_no_scene(client):
    from test_app import make_verified, user_login
    make_verified(client, "employer", "hr@acme.example"); user_login(client, "employer", "hr@acme.example")
    assert 'data-scan' not in client.get("/").text


def test_demo_embeds_the_same_scene():
    import json, showcase
    demo = (ROOT / "demo" / "NoleCareerShield_Demo.html").read_text()
    safe = json.dumps(showcase.scan_template(), separators=(",", ":")).replace("</", "<\\/")
    assert "var NCS_SCAN = " + safe + ";" in demo, "run python demo/build.py"
    assert (ROOT / "static" / "scan.js").read_text() in demo and "data:font/woff2;base64," in demo
