"""TC-SV3-F1~F12: Screener V3 frontend spec (unit-testable assertions).

These tests verify the HTML structure and JS behavior expectations
without requiring a running browser. For full E2E, use Playwright.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


TEMPLATE_PATH = Path(__file__).parent.parent.parent / "stock_trading_system/web/templates/index.html"
JS_PATH = Path(__file__).parent.parent.parent / "stock_trading_system/web/static/js/screener_v3.js"


@pytest.fixture()
def html():
    return TEMPLATE_PATH.read_text()


@pytest.fixture()
def js():
    return JS_PATH.read_text()


class TestF1_PageTitle:
    def test_v3_title(self, html):
        assert "智能选股 V3 · 大师 Agent" in html


class TestF2_NLInput:
    def test_textarea_present(self, html):
        assert 'id="screen-nl-query"' in html
        assert "textarea" in html.lower()


class TestF3_GuruCheckboxes:
    def test_checkbox_container(self, html):
        assert 'id="v3-guru-checkboxes"' in html

    def test_quick_select_buttons(self, html):
        assert "v3SelectGurus" in html
        assert "全选" in html
        assert "推荐 4" in html
        assert "全不选" in html


class TestF4_ModeSelection:
    def test_three_modes(self, html):
        assert "经典阈值" in html
        assert "Agent 深度" in html
        assert "Agent + 圆桌辩论" in html

    def test_radio_inputs(self, html):
        assert 'value="classic"' in html
        assert 'value="agent"' in html
        assert 'value="agent_with_roundtable"' in html


class TestF5_CandidateChips:
    def test_candidate_counts(self, html):
        assert 'data-n="10"' in html
        assert 'data-n="20"' in html
        assert 'data-n="30"' in html
        assert 'data-n="50"' in html


class TestF6_EstimateDisplay:
    def test_estimate_card(self, html):
        assert 'id="v3-estimate-card"' in html
        assert 'id="v3-est-calls"' in html
        assert 'id="v3-est-duration"' in html
        assert 'id="v3-est-cost"' in html


class TestF7_TriggerButton:
    def test_start_button(self, html):
        assert 'id="btn-screen-v3"' in html
        assert "runScreenV3" in html


class TestF8_ProgressCard:
    def test_progress_elements(self, html):
        assert 'id="v3-progress-card"' in html
        assert 'id="v3-progress-bar"' in html
        assert 'id="v3-stream-list"' in html


class TestF9_ResultsCard:
    def test_result_elements(self, html):
        assert 'id="v3-results-card"' in html
        assert 'id="v3-results-list"' in html


class TestF10_JSEstimateWiring:
    def test_debounce_estimate(self, js):
        assert "screen/v3/estimate" in js
        assert "500" in js  # debounce ms

    def test_trigger_call(self, js):
        assert "screen/v3/trigger" in js


class TestF11_LocalStoragePersistence:
    def test_save_and_restore(self, js):
        assert "localStorage" in js
        assert "screener_v3_config" in js


class TestF12_FirstUseTip:
    def test_tooltip_present(self, html):
        assert 'id="v3-first-use-tip"' in html
        assert "V3 大师评估已启用" in html
        assert "v3_tip_dismissed" in html
