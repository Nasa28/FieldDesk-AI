from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.db_queries.tenant_budgets import BudgetUsage
    from fielddesk_worker.jobs import budget as budget_mod
    from fielddesk_worker.jobs import queue as queue_mod
    from fielddesk_worker.jobs.reliability import (
        BUDGET_GATED_JOB_TYPES,
        is_budget_gated_job,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


def _usage(**overrides) -> BudgetUsage:
    base = dict(
        tenant_id="t-1",
        daily_budget_usd=None,
        monthly_budget_usd=None,
        max_cost_per_ticket=None,
        pause_on_exceeded=True,
        daily_spend_usd=0.0,
        monthly_spend_usd=0.0,
        daily_over=False,
        monthly_over=False,
    )
    base.update(overrides)
    return BudgetUsage(**base)


class BudgetGatingTests(unittest.TestCase):
    def test_gated_types_match_billed_providers(self):
        # draft_ticket must be excluded — it's a pure DB write.
        self.assertEqual(
            BUDGET_GATED_JOB_TYPES, {"transcribe", "extract", "embed", "rag"}
        )
        self.assertFalse(is_budget_gated_job("draft_ticket"))
        self.assertTrue(is_budget_gated_job("extract"))

    def test_should_block_only_when_paused_and_over(self):
        # No limits → never blocks.
        self.assertFalse(_usage().should_block())
        # Pause off → never blocks even if over.
        self.assertFalse(
            _usage(
                pause_on_exceeded=False,
                daily_budget_usd=10.0,
                daily_spend_usd=20.0,
                daily_over=True,
            ).should_block()
        )
        # Pause on + daily over → blocks.
        self.assertTrue(
            _usage(
                daily_budget_usd=10.0,
                daily_spend_usd=20.0,
                daily_over=True,
            ).should_block()
        )
        # Pause on + monthly over → blocks.
        self.assertTrue(
            _usage(
                monthly_budget_usd=100.0,
                monthly_spend_usd=200.0,
                monthly_over=True,
            ).should_block()
        )

    def test_block_detail_summarizes_which_cap(self):
        only_daily = _usage(
            daily_budget_usd=10.0, daily_spend_usd=12.0, daily_over=True
        )
        detail = budget_mod.block_detail(only_daily)
        self.assertIn("daily", detail)
        self.assertNotIn("monthly", detail)

        both = _usage(
            daily_budget_usd=10.0, daily_spend_usd=12.0, daily_over=True,
            monthly_budget_usd=100.0, monthly_spend_usd=120.0, monthly_over=True,
        )
        detail = budget_mod.block_detail(both)
        self.assertIn("daily", detail)
        self.assertIn("monthly", detail)

        # Defensive: should_block can be true even if neither *_over flag is
        # individually set if someone calls the helper on a stale snapshot —
        # the detail string still says budget_exceeded rather than blowing up.
        self.assertEqual(budget_mod.block_detail(_usage()), "budget_exceeded")

    def test_blocked_path_skips_handler_and_routes_to_review(self):
        job = {
            "id": "job-1",
            "tenant_id": "t-1",
            "type": "transcribe",
            "max_attempts": 5,
        }
        payload = {"voice_note_id": "vn-1"}

        over = _usage(
            daily_budget_usd=5.0, daily_spend_usd=6.0, daily_over=True
        )
        with patch.object(budget_mod, "read_budget_usage", return_value=over), \
             patch.object(budget_mod, "mark_budget_blocked") as mark_mock, \
             patch.object(budget_mod, "conn") as conn_mock:
            cm = MagicMock()
            conn_mock.return_value.__enter__.return_value = cm
            cm.transaction.return_value.__enter__.return_value = None
            cm.cursor.return_value.__enter__.return_value = MagicMock()

            blocked = budget_mod.is_blocked(job, payload, attempt_number=1)

            self.assertTrue(blocked)
            mark_mock.assert_called_once()
            self.assertEqual(mark_mock.call_args.args[3], 1)

    def test_under_budget_does_not_block(self):
        job = {"id": "job-2", "tenant_id": "t-1", "type": "extract", "max_attempts": 5}
        usage = _usage(daily_budget_usd=10.0, daily_spend_usd=1.0)

        with patch.object(budget_mod, "read_budget_usage", return_value=usage), \
             patch.object(budget_mod, "mark_budget_blocked") as mark_mock, \
             patch.object(budget_mod, "conn") as conn_mock:
            cm = MagicMock()
            conn_mock.return_value.__enter__.return_value = cm

            self.assertFalse(budget_mod.is_blocked(job, {}, attempt_number=1))
            mark_mock.assert_not_called()

    def test_unknown_tenant_returns_none_and_does_not_block(self):
        # read_budget_usage returns None when the tenant doesn't exist; we
        # must not throw or accidentally block.
        job = {"id": "job-3", "tenant_id": "missing", "type": "embed", "max_attempts": 5}
        with patch.object(budget_mod, "read_budget_usage", return_value=None), \
             patch.object(budget_mod, "mark_budget_blocked") as mark_mock, \
             patch.object(budget_mod, "conn") as conn_mock:
            cm = MagicMock()
            conn_mock.return_value.__enter__.return_value = cm

            self.assertFalse(budget_mod.is_blocked(job, {}, attempt_number=1))
            mark_mock.assert_not_called()

    def test_non_gated_job_skips_db_entirely(self):
        # draft_ticket should never touch the budget view — saves a query
        # on the hot path.
        job = {"id": "job-4", "tenant_id": "t-1", "type": "draft_ticket", "max_attempts": 5}
        with patch.object(budget_mod, "read_budget_usage") as read_mock, \
             patch.object(budget_mod, "conn") as conn_mock:
            self.assertFalse(budget_mod.is_blocked(job, {}, attempt_number=1))
            read_mock.assert_not_called()
            conn_mock.assert_not_called()

    def test_budget_read_error_uses_normal_failure_path(self):
        job = {
            "id": "job-5",
            "tenant_id": "t-1",
            "type": "extract",
            "attempt_count": 1,
            "max_attempts": 5,
            "payload": {},
        }
        settings = MagicMock(job_lease_seconds=30)
        heartbeat_stop = MagicMock()
        heartbeat_thread = MagicMock()

        with patch.object(queue_mod, "load_settings", return_value=settings), \
             patch.object(queue_mod, "_claim_next_job", return_value=job), \
             patch.object(queue_mod, "start_heartbeat", return_value=(heartbeat_stop, heartbeat_thread)), \
             patch.object(queue_mod, "is_budget_blocked", side_effect=RuntimeError("budget view unavailable")), \
             patch.object(queue_mod, "conn") as conn_mock, \
             patch.object(queue_mod, "_record_attempt") as record_mock, \
             patch.object(queue_mod, "_mark_failed_or_retry", return_value="retrying") as fail_mock:
            cm = MagicMock()
            conn_mock.return_value.__enter__.return_value = cm

            self.assertEqual(queue_mod.process_one(), 1)

            record_mock.assert_called_once()
            self.assertEqual(record_mock.call_args.args[3], "failed")
            fail_mock.assert_called_once()
            heartbeat_stop.set.assert_called_once()
            heartbeat_thread.join.assert_called_once_with(timeout=2)


if __name__ == "__main__":
    unittest.main()
