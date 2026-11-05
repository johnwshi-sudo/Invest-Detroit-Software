"""Golden test against Invest Detroit's sample Investment Summaries.

Runs only where the gitignored sample fixtures exist (samples/fixtures/). See scripts/validate_samples.py.
"""
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parents[1] / "samples" / "fixtures"
pytestmark = pytest.mark.skipif(not (FIX / "expected_values.py").exists(), reason="sample fixtures not present (borrower data is not committed)")


def test_every_sample_figure_reproduced_or_explained():
    import sys
    sys.path.insert(0, str(FIX.parents[1] / "scripts"))
    from validate_samples import validate
    R = validate()
    diffs = [r for r in R.rows if r[3] == "DIFF"]
    assert not diffs, diffs
    assert sum(1 for r in R.rows if r[3] == "exact") >= 340
