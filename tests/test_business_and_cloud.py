import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harrowgate import cloud, roi
from harrowgate.providers import PROVIDERS, make_provider

ROOT = Path(__file__).resolve().parents[1]
M = roi.Measured(containment=0.8, error_reduction=0.9, model_cost_per_request=0.0002)


def test_roi_arithmetic_matches_the_formula():
    a = roi.Assumptions(1000, 10, 2, 10, 60, 0.05, 100, 500, 5, 4000)
    r = roi.monthly(a, M)
    hours = (800 * 8) / 60
    value = hours * 60 + 1000 * 0.05 * 100 * 0.9
    run = 1000 * 0.0002 + 500
    assert r["staff_hours_saved"] == round(hours, 1) and r["value_usd"] == round(value)
    assert r["run_cost_usd"] == round(run) and r["net_usd"] == round(value - run)
    assert r["payback_months"] == round(20000 / (value - run), 1)


def test_sensitivity_is_ordered_low_base_high():
    for a in roi.DOMAINS.values():
        s = roi.sensitivity(a, M)
        assert s["low"]["net_usd"] < s["base"]["net_usd"] < s["high"]["net_usd"]


def test_negative_net_has_no_payback():
    a = roi.Assumptions(10, 1, 1, 1, 10, 0, 0, 5000, 5)
    assert roi.monthly(a, M)["payback_months"] is None and roi.break_even_volume(a, M) is None


def test_slower_review_reduces_the_value():
    fast = roi.Assumptions(1000, 10, 2, 10, 60, 0.0, 0, 0, 1)
    slow = roi.Assumptions(1000, 10, 2, 30, 60, 0.0, 0, 0, 1)
    assert roi.monthly(slow, M)["value_usd"] < roi.monthly(fast, M)["value_usd"]


def test_break_even_volume_really_breaks_even():
    a = roi.DOMAINS["retail"]
    v = roi.break_even_volume(a, M)
    from dataclasses import replace
    assert roi.monthly(replace(a, monthly_volume=v), M)["net_usd"] >= 0
    assert roi.monthly(replace(a, monthly_volume=max(1, v - 50)), M)["net_usd"] < 1


def test_every_domain_has_assumptions_a_mix_and_a_kpi():
    for k, mix in roi.MIX.items():
        assert abs(sum(mix.values()) - 1) < 1e-9 and set(mix) == set(roi.KINDS)
        assert k in roi.DOMAINS and k in roi.KPI_NAMES
    assert roi.containment({"routine": 1.0}, {"routine": 0.5}) == 0.5


def test_cloud_costs_scale_and_self_hosting_has_no_token_cost():
    rows = cloud.compare([10_000, 1_000_000], 90, 30)
    az = [r for r in rows if r["option"] == "azure"]
    assert az[1]["tokens"] == pytest.approx(100 * az[0]["tokens"], rel=1e-6)
    onprem = [r for r in rows if r["option"] == "onprem"]
    assert all(r["tokens"] == 0 for r in onprem) and onprem[0]["over_capacity"] is False
    assert cloud.AS_OF in cloud.LABEL


def test_provider_factory_defaults_to_mock_and_rejects_unknown_names():
    assert make_provider().name == "mock"
    assert set(PROVIDERS) == {"mock", "azure", "aws", "gcp", "selfhosted"}
    with pytest.raises(ValueError):
        make_provider("other")


def test_core_imports_no_cloud_sdk():
    code = ("import sys, harrowgate.system, harrowgate.packs.engine, harrowgate.providers;"
            "print([m for m in ('boto3', 'google', 'azure') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                         env={**os.environ, "PYTHONPATH": str(ROOT)}, check=True).stdout.strip()
    assert out == "[]"


def test_generated_results_cover_every_layer_and_domain():
    r = json.loads((ROOT / "results/packs.json").read_text())
    assert len(r["packs"]) == 8 and set(r["roi"]) == set(r["packs"])
    matrix = (ROOT / "docs/benefits-matrix.md").read_text()
    rows = [line for line in matrix.splitlines() if line[:4] in {f"| {i}." for i in range(1, 10)} or
            line[:5] in {f"| {i}." for i in range(10, 22)}]
    assert len(rows) == 21 and all(line.count("|") == 11 for line in rows)
    for doc in ("business-roi.md", "executive-summary.md", "cloud-options.md"):
        text = (ROOT / "docs" / doc).read_text().lower()
        assert "assum" in text or "estimate" in text


def test_policy_key_prefers_a_mounted_secret_file(tmp_path, monkeypatch):
    from harrowgate.policy import policy_key
    f = tmp_path / "k"
    f.write_text("file-key\n")
    monkeypatch.setenv("HARROWGATE_POLICY_KEY_FILE", str(f))
    monkeypatch.setenv("HARROWGATE_POLICY_KEY", "env-key")
    assert policy_key() == b"file-key"
    monkeypatch.delenv("HARROWGATE_POLICY_KEY_FILE")
    assert policy_key() == b"env-key"
    monkeypatch.delenv("HARROWGATE_POLICY_KEY")
    assert len(policy_key()) == 32
