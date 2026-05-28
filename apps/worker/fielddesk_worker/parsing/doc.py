from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fielddesk_worker.parsing.base import ParseError, ParsedSegment


# Hard timeout for the libreoffice subprocess. .doc → .docx conversion is
# normally sub-second, but libreoffice has historical edge cases where it
# spawns a hung profile lock and waits indefinitely on user input. Killing
# after 60s prevents the embed job from holding a lease forever.
_LIBREOFFICE_TIMEOUT_SEC = 60


def parse_doc(content: bytes) -> list[ParsedSegment]:
    """Legacy Word (.doc, OLE binary) parser.

    Strategy: shell out to libreoffice in headless mode to convert
    .doc → .docx, then dispatch to the existing python-docx parser. We
    don't try to parse the OLE binary format directly — the available
    pure-Python options (olefile, python-mso) are either incomplete
    (text only, no styles → loses heading_path) or unmaintained.

    libreoffice is the standard answer in the office-doc-conversion
    world: pandoc has known regressions on .doc, antiword is abandoned,
    textract pulls in too many transitive deps. The tradeoff is a
    larger worker image (~400MB for libreoffice-core + libreoffice-writer).

    Requires the `soffice` binary on PATH — installed in worker.Dockerfile.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        raise ParseError(
            ".doc parsing requires libreoffice "
            "(install libreoffice-core + libreoffice-writer in the worker image)"
        )

    with tempfile.TemporaryDirectory(prefix="fielddesk-doc-") as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / "input.doc"
        input_path.write_bytes(content)
        try:
            result = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to", "docx",
                    "--outdir", str(tmp_path),
                    str(input_path),
                ],
                # A dedicated user profile dir per call prevents the
                # "another office instance is running" error when two
                # worker pods invoke soffice simultaneously.
                env={**os.environ, "HOME": str(tmp_path)},
                capture_output=True,
                timeout=_LIBREOFFICE_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ParseError(
                f".doc → .docx conversion timed out after {_LIBREOFFICE_TIMEOUT_SEC}s "
                "(libreoffice may be hung; check for stale profile locks)"
            ) from e

        if result.returncode != 0:
            stderr_tail = (result.stderr or b"").decode("utf-8", errors="replace")[-500:]
            raise ParseError(
                f"libreoffice exit {result.returncode} converting .doc → .docx: {stderr_tail}"
            )

        # libreoffice names the output after the input stem.
        docx_path = tmp_path / "input.docx"
        if not docx_path.is_file():
            # Some libreoffice versions write to a different filename when
            # the input has non-ASCII characters or weird metadata. Pick
            # the first .docx in the outdir as a fallback.
            candidates = list(tmp_path.glob("*.docx"))
            if not candidates:
                raise ParseError(
                    ".doc → .docx conversion produced no output file"
                )
            docx_path = candidates[0]

        # Hand off to the existing docx parser so heading_path, table
        # extraction, and segment shape stay identical to a native .docx
        # upload.
        from fielddesk_worker.parsing.docx import parse_docx

        return parse_docx(docx_path.read_bytes())
