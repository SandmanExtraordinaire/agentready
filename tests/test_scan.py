import json

from agentready.discover import classify
from agentready.checks.discoverability import price_variants
from agentready.report import render_html
from agentready.scanner import scan
from agentready.ucp_schema import available_versions, validate_profile

from .conftest import FIXTURES


def run(base, **kw):
    return scan(base, use_browser=False, delay=0, log=lambda *_: None, **kw)


def statuses(result):
    return {f.id: f.status.value for f in result.findings}


def test_classify():
    assert classify("https://x.com/products/shoe") == "product"
    assert classify("https://x.com/collections/shoes/products/shoe") == "product"
    assert classify("https://x.com/collections/shoes") == "category"
    assert classify("https://x.com/dp/B08N5WRWNW") == "product"
    assert classify("https://x.com/about") == "other"
    assert classify("https://x.com/img/a.jpg") == "asset"


def test_price_variants():
    assert "129.00" in price_variants("129.00")
    assert "1,299.00" in price_variants(1299)
    assert "1.299,00" in price_variants("1299.00")


def test_ucp_validation_follows_declared_version():
    profile = json.loads((FIXTURES / "ucp_profile_valid.json").read_text())
    assert len(available_versions()) >= 4
    assert validate_profile(profile) == ("2026-08-25", [])
    del profile["ucp"]["payment_handlers"]
    _, errors = validate_profile(profile)
    assert any("payment_handlers" in e for e in errors)
    profile["ucp"]["version"] = "2026-01-11"         # shape mismatch against the old schema
    assert validate_profile(profile)[0] == "2026-01-11"


def test_good_store_reaches_transactable_or_better(good_store):
    r = run(good_store)
    s = statuses(r)
    assert s["robots_ai_agents"] == "pass"          # GPTBot block is training-only, not penalised
    assert s["bot_wall"] == "pass"
    assert s["ucp_profile"] == "pass"
    assert s["ucp_checkout"] == "pass"
    assert s["ucp_endpoints"] == "pass"
    assert s["mcp_server"] == "pass"
    assert s["a2a_card"] == "pass"
    assert s["product_schema"] == "pass"
    assert s["offer_fields"] == "pass"
    assert s["identifiers"] == "pass"
    assert s["policies"] == "pass"
    assert s["price_consistency"] == "pass"
    assert s["raw_html"] == "pass"
    assert s["llms_txt"] == "pass"
    assert s["task_add_to_cart"] == "skip"          # no browser in tests
    assert r.tier == "Agent-native"
    assert r.score > 85
    mcp = r.finding("mcp_server")
    assert "create_checkout" in mcp.data["tools"]


def test_walled_store_is_invisible(walled_store):
    r = run(walled_store, product_urls=[walled_store + "/products/thing"])
    s = statuses(r)
    assert s["robots_ai_agents"] == "fail"
    assert s["bot_wall"] == "fail"
    assert s["ucp_profile"] == "fail"
    assert s["product_schema"] == "fail"
    assert s["raw_html"] == "fail"
    assert s["cart_access"] == "fail"
    assert r.tier == "Invisible"
    assert r.score < 25


def test_report_renders_with_competitor(good_store):
    a = run(good_store)
    b = run(good_store)
    b.domain = "rival.example"
    html = render_html([a, b])
    assert "Fix these first" in html or a.score == 100
    assert "Against the competition" in html and "rival.example" in html
    assert "<script>alert" not in html
