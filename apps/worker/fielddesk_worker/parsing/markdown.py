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
    # heading_stack[i] = heading text at level i+1 (1-indexed). Length tracks
    # the current depth; assigning a new heading at level N truncates anything
    # deeper.
    heading_stack: list[str] = []
    current_body: list[str] = []
    in_fence = False

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
            flush(heading_stack)
            level = len(m.group(1))
            title = m.group(2).strip()
            # Truncate stack to the new heading's parent, then push.
            del heading_stack[level - 1 :]
            heading_stack.append(title)
        else:
            current_body.append(line)
    flush(heading_stack)
    return segments
