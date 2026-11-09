import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_brands  # noqa: E402
import check_numbers  # noqa: E402
import count_tests  # noqa: E402


def test_brand_check_flags_a_hashed_term_without_storing_it():
    h_term, h_spell = check_brands.digest("zebracorp"), check_brands.digest("Zebracorp")
    assert check_brands.find_hits("we use Zebracorp here", {h_term}, {h_spell}) == ["Zebracorp"]
    assert check_brands.find_hits("we use zebracorp here", {h_term}, {h_spell}) == []


def test_number_marker_check():
    metrics = {"a": {"rate": 0.953}}
    assert check_numbers.check_text("success **95.3%**<!-- m:a.rate -->", metrics) == []
    assert check_numbers.check_text("success **90.0%**<!-- m:a.rate -->", metrics)


def test_count_parser():
    assert count_tests.parse_count("135 tests collected in 0.4s") == 135


def test_fictional_names_only_in_world_data():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/check_brands.py")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
