"""Formal product entry must not expose an Agent 1/2-only demo path."""
import re
import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("viewport", [{"width": 1724, "height": 864}, {"width": 390, "height": 844}])
def test_product_entry_uses_normal_forecast_workflow(page, app_url, viewport):
    page.set_viewport_size(viewport)
    writes = []
    page.on("request", lambda r: writes.append(r.url) if r.method == "POST" else None)
    page.goto(app_url)

    expect(page.get_by_role("button", name="体验问题与证据新流程", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("^运行教学演示"))).to_be_visible()
    expect(page.get_by_placeholder("例如：某产品能否在 12 月 20 日前发布正式版？")).to_be_visible()
    expect(page.get_by_role("button", name="分析问题", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="开始预测 →", exact=True)).to_be_disabled()
    assert writes == [], "Opening the formal create page must not start analysis or prediction automatically"
