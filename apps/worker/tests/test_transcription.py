from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.providers.base import TranscriptionResult
    from fielddesk_worker.transcription import service
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


class _Provider:
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> TranscriptionResult:
        return TranscriptionResult(
            text="fixed transcript",
            provider="stub",
            model="stub-transcriber-v1",
            duration_ms=7,
            cost_usd=0.0,
            language="en",
            metadata={"bytes": len(audio_bytes), "mime_type": mime_type},
        )


class TranscriptionTests(unittest.TestCase):
    def test_transcribe_rejects_payload_tenant_mismatch(self) -> None:
        job = {
            "id": "job-1",
            "tenant_id": "tenant-a",
            "payload": {
                "tenant_id": "tenant-b",
                "voice_note_id": "voice-note-1",
                "object_key": "tenants/tenant-b/voice-notes/voice-note-1/audio.mp3",
            },
        }

        with self.assertRaisesRegex(ValueError, "tenant_id"):
            service.transcribe(job, cur=object())

    def test_transcribe_uses_job_tenant_and_database_voice_note(self) -> None:
        calls: dict[str, object] = {}

        def get_voice_note_for_update(cur, *, voice_note_id, tenant_id):
            calls["voice_note_lookup"] = (voice_note_id, tenant_id)
            return {
                "id": voice_note_id,
                "tenant_id": tenant_id,
                "object_key": "tenants/tenant-a/voice-notes/voice-note-1/audio.mp3",
                "mime_type": "audio/mpeg",
                "status": "uploaded",
                "size_bytes": 5,
            }

        patches = [
            patch.object(service, "get_voice_note_for_update", get_voice_note_for_update),
            patch.object(service, "_make_provider", lambda: _Provider()),
            patch.object(service, "object_exists", lambda key: True),
            patch.object(service, "get_object_bytes", lambda key: b"audio"),
            patch.object(service, "insert_transcript", lambda *args, **kwargs: "transcript-1"),
            patch.object(service, "insert_model_call", lambda *args, **kwargs: "call-1"),
            patch.object(service, "update_voice_note_status", lambda *args, **kwargs: None),
            patch.object(service, "enqueue_job", lambda *args, **kwargs: "job-2"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        result = service.transcribe(
            {
                "id": "job-1",
                "tenant_id": "tenant-a",
                "payload": {
                    "tenant_id": "tenant-a",
                    "voice_note_id": "voice-note-1",
                    "object_key": "tenants/tenant-a/voice-notes/voice-note-1/audio.mp3",
                },
            },
            cur=object(),
        )

        self.assertEqual(calls["voice_note_lookup"], ("voice-note-1", "tenant-a"))
        self.assertEqual(result["transcript_id"], "transcript-1")
        self.assertEqual(result["next_job_id"], "job-2")


if __name__ == "__main__":
    unittest.main()
