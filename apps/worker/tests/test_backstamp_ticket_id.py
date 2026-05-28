"""Worker test for the ticket-id back-stamp helper.

DB-backed extraction tests aren't in scope for this slice (the rest of the
codebase doesn't run testcontainers either), so we exercise the helper
against a MagicMock cursor and lock in the invariants that matter:

  * It UPDATEs ai_model_calls, not anything else.
  * It only stamps rows whose ticket_id IS NULL — never overwrites a row
    that was already attributed (e.g. by recs synthesis running after a
    prior extraction was re-resolved).
  * It scopes by tenant AND by voice_note_id pulled from request_meta JSONB.
  * The params are passed in the order the SQL expects them.

If any of these change without intent, the test fails — and that's the
point: the worker's promise to the DB layer is small and easy to break.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.db_queries.ai_model_calls import (
        backstamp_model_call_ticket_id,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


class BackstampTicketIDTests(unittest.TestCase):
    def test_executes_update_against_ai_model_calls(self):
        cur = MagicMock()
        cur.rowcount = 3
        rows = backstamp_model_call_ticket_id(
            cur,
            tenant_id="t-1",
            voice_note_id="vn-9",
            ticket_id="tk-42",
        )
        cur.execute.assert_called_once()
        sql, params = cur.execute.call_args.args
        self.assertIn("UPDATE ai_model_calls", sql)
        self.assertEqual(rows, 3)
        # Params: ticket_id, tenant_id, voice_note_id — order matches the
        # SQL's %s placeholders.
        self.assertEqual(params, ("tk-42", "t-1", "vn-9"))

    def test_only_stamps_rows_with_null_ticket_id(self):
        # Anti-regression: if someone drops the IS NULL guard, the helper
        # would silently overwrite already-attributed rows (e.g. a recs
        # synthesis call that already carries the right ticket_id) with
        # whatever ticket the extraction job is dealing with — wrong if
        # the same voice note ever feeds two tickets via re-extraction.
        cur = MagicMock()
        cur.rowcount = 0
        backstamp_model_call_ticket_id(
            cur,
            tenant_id="t-1",
            voice_note_id="vn-9",
            ticket_id="tk-42",
        )
        sql, _ = cur.execute.call_args.args
        self.assertIn("ticket_id IS NULL", sql)

    def test_filters_by_tenant_and_voice_note_request_meta(self):
        cur = MagicMock()
        cur.rowcount = 0
        backstamp_model_call_ticket_id(
            cur,
            tenant_id="t-1",
            voice_note_id="vn-9",
            ticket_id="tk-42",
        )
        sql, _ = cur.execute.call_args.args
        self.assertIn("tenant_id = %s", sql)
        self.assertIn("request_meta->>'voice_note_id' = %s", sql)

    def test_returns_rowcount_for_logging(self):
        # The caller (extraction service) logs the back-stamped count for
        # operator visibility, so the helper must surface cur.rowcount,
        # not e.g. 0 or None.
        cur = MagicMock()
        cur.rowcount = 7
        self.assertEqual(
            backstamp_model_call_ticket_id(
                cur, tenant_id="t-1", voice_note_id="vn-9", ticket_id="tk-42",
            ),
            7,
        )


if __name__ == "__main__":
    unittest.main()
