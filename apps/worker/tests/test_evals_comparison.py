"""Phase 5 prompt-version comparison — delta math + CLI behavior.

Mocks `run_extraction_evals` so we don't pay for an actual OpenAI run on
every test invocation. The live behavior (whether v2.ablation actually
scores worse than v1 against real attacks) is verified by the eval CLI
itself when an operator runs `--compare`; these tests cover the
infrastructure that turns the two runs into a regression signal.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.evals.comparison import (
        ComparisonReport,
        VersionResult,
        render_report,
        run_extraction_comparison,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


def _fake_metrics(rate: float) -> dict:
    """Shape that matches what run_extraction_evals actually returns; the
    comparison module only needs `injection_resistance_rate` and `cases`,
    but mirror the production shape so a future change to the contract
    fails loudly here instead of in production."""
    return {
        "injection_resistance_rate": rate,
        "prompt_version": "ignored-by-comparison",  # comparison passes it in explicitly
        "cases": [{"name": f"case_{i}", "passed": True} for i in range(3)],
    }


class ReportMathTests(unittest.TestCase):
    def test_baseline_delta_is_zero(self):
        report = ComparisonReport(
            tenant_id="t-1",
            baseline_version="A",
            versions=[
                VersionResult("A", "h1", 0.8, 3, 1.0),
                VersionResult("B", "h2", 0.6, 3, 1.0),
            ],
        )
        deltas = report.deltas()
        # First entry is the baseline; its delta should be exactly 0.0 so a
        # rendered "+0.000" doesn't mislead.
        self.assertEqual(deltas[0][0].prompt_version, "A")
        self.assertAlmostEqual(deltas[0][1], 0.0)
        # Candidate scored lower → delta negative.
        self.assertAlmostEqual(deltas[1][1], -0.2)

    def test_regressed_true_when_candidate_below_baseline(self):
        report = ComparisonReport(
            tenant_id="t-1",
            baseline_version="A",
            versions=[
                VersionResult("A", "h1", 0.8, 3, 1.0),
                VersionResult("B", "h2", 0.6, 3, 1.0),
            ],
        )
        self.assertTrue(report.regressed())

    def test_regressed_threshold_allows_small_drop(self):
        # 0.05 drop tolerance, 0.04 actual drop → not a regression.
        report = ComparisonReport(
            tenant_id="t-1",
            baseline_version="A",
            versions=[
                VersionResult("A", "h1", 0.80, 3, 1.0),
                VersionResult("B", "h2", 0.76, 3, 1.0),
            ],
        )
        self.assertFalse(report.regressed(threshold=0.05))
        self.assertTrue(report.regressed(threshold=0.03))

    def test_regressed_false_when_candidate_higher(self):
        report = ComparisonReport(
            tenant_id="t-1",
            baseline_version="A",
            versions=[
                VersionResult("A", "h1", 0.6, 3, 1.0),
                VersionResult("B", "h2", 0.9, 3, 1.0),
            ],
        )
        self.assertFalse(report.regressed())

    def test_render_report_marks_baseline_and_regression(self):
        report = ComparisonReport(
            tenant_id="t-1",
            baseline_version="A",
            versions=[
                VersionResult("A", "h1", 0.8, 3, 1.0),
                VersionResult("B", "h2", 0.6, 3, 1.0),
            ],
        )
        text = render_report(report)
        self.assertIn("baseline A", text)
        # Baseline row shows "base", not a delta number.
        self.assertIn("  base", text)
        # Candidate row carries a negative delta and the regression banner.
        self.assertIn("-0.200", text)
        self.assertIn("REGRESSION", text)

    def test_render_report_respects_regression_threshold(self):
        report = ComparisonReport(
            tenant_id="t-1",
            baseline_version="A",
            versions=[
                VersionResult("A", "h1", 0.80, 3, 1.0),
                VersionResult("B", "h2", 0.76, 3, 1.0),
            ],
        )
        text = render_report(report, threshold=0.05)
        self.assertNotIn("REGRESSION", text)
        self.assertIn("within threshold 0.050", text)


class RunExtractionComparisonTests(unittest.TestCase):
    def test_runs_each_version_once_and_aggregates(self):
        # Two known prompt versions; mocked run_extraction_evals returns a
        # different rate per version so we can assert ordering + delta math.
        rates = {
            "extract.v1.injection-hardened": 0.92,
            "extract.v2.ablation": 0.55,
        }

        def fake_run(tenant_id, *, prompt_version):
            return _fake_metrics(rates[prompt_version])

        with patch(
            "fielddesk_worker.evals.comparison.run_extraction_evals",
            side_effect=fake_run,
        ) as mock_run:
            report = run_extraction_comparison(
                "t-1",
                ["extract.v1.injection-hardened", "extract.v2.ablation"],
            )

        # Each version was run exactly once.
        self.assertEqual(mock_run.call_count, 2)
        # Baseline defaults to the first entry.
        self.assertEqual(report.baseline_version, "extract.v1.injection-hardened")
        # Candidate (v2) regressed against baseline (v1).
        self.assertTrue(report.regressed())
        # Hashes are populated from the real registry (not from rates).
        v2 = next(v for v in report.versions if v.prompt_version == "extract.v2.ablation")
        self.assertEqual(len(v2.prompt_hash), 16)

    def test_rejects_unknown_prompt_version(self):
        with self.assertRaises(KeyError) as ctx:
            run_extraction_comparison("t-1", ["extract.vNOPE", "extract.v1.injection-hardened"])
        self.assertIn("vNOPE", str(ctx.exception))

    def test_rejects_empty_versions_list(self):
        with self.assertRaises(ValueError):
            run_extraction_comparison("t-1", [])

    def test_baseline_must_be_in_compare_list(self):
        with self.assertRaises(ValueError):
            run_extraction_comparison(
                "t-1",
                ["extract.v1.injection-hardened", "extract.v2.ablation"],
                baseline_version="extract.vNOT-IN-LIST",
            )


if __name__ == "__main__":
    unittest.main()
