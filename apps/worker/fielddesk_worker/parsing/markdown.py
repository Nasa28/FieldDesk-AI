from __future__ import annotations

import re

from fielddesk_worker.parsing.base import ParseError, ParsedSegment


# ATX headings only (#, ##, ###, ...). Setext (=== / ---) is rare in tooling
# output and pulling it in adds parser complexity we don't need yet. If a
# corpus shows up that uses setext, extend here rather than dropping a
# dependency on a full markdown parser.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

# Skip code fences when looking for headings — a `# comment` line inside a
# fenced code block is not a heading. Track fence state across lines.
_FENCE_RE = re.compile(r"^```")


def parse_markdown(content: bytes) -> list[ParsedSegment]:
    """Heading-aware markdown parser.

    Emits one ParsedSegment per "section" — a heading plus its body, with
    `heading_path` being the trail from the top-level heading down to the
    most recent one at this level. This preserves citation context: a chunk
    inside "## Troubleshooting > ### Pressure Loss" stays distinguishable
    from one inside "## Maintenance > ### Lubrication" even after splitting.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ParseError(f"could not decode markdown as utf-8: {e}") from e

    lines = text.splitlines()
    segments: list[ParsedSegment] = []
    # Preserve actual heading levels. A document can start at H2; that should
    # not make later H2 headings children of the first H2.
    headings_by_level: dict[int, str] = {}
    current_body: list[str] = []
    in_fence = False

    def current_path() -> list[str]:
        return [headings_by_level[level] for level in sorted(headings_by_level)]

    def flush(path: list[str]) -> None:
        body = "\n".join(current_body).strip()
        if body:
            segments.append(ParsedSegment(text=body, heading_path=list(path)))
        current_body.clear()

    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current_body.append(line)
            continue
        if in_fence:
            current_body.append(line)
            continue
        m = _HEADING_RE.match(line)
        if m:
            # Persist the section accumulated before this heading.
            flush(current_path())
            level = len(m.group(1))
            title = m.group(2).strip()
            # Truncate stack to the new heading's parent, then push.
            for existing_level in list(headings_by_level):
                if existing_level >= level:
                    del headings_by_level[existing_level]
            headings_by_level[level] = title
        else:
            current_body.append(line)
    flush(current_path())
    return segments
