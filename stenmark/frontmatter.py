# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import re

import yaml

from stenmark.note_file import read_note, save_note


# Opening --- (with optional trailing whitespace), content, closing ---
_FRONTMATTER = re.compile(r"^---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?\n", re.DOTALL)
_TAGS_KEY = re.compile(r"""["']?tags["']?[ \t]*:""")


def parse_frontmatter(text):
    """Return (metadata_dict, body_without_frontmatter).

    If no valid frontmatter, returns ({}, original_text).
    Frontmatter = text between opening ``---\\n`` and closing ``---\\n``
    at the very start of the file.
    """
    if not text.startswith("---"):
        return {}, text

    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text

    yaml_block = m.group(1)
    body = text[m.end():]

    try:
        meta = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return {}, text

    if not isinstance(meta, dict):
        return {}, text

    return meta, body


def read_tags(path):
    """Open file, extract tags list from frontmatter, return [] if none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(8192)  # read enough to cover frontmatter
    except OSError:
        return []

    meta, _ = parse_frontmatter(text)
    return _extract_tags(meta)


def _extract_tags(meta):
    """Extract tags from metadata dict as lowercase stripped strings."""
    raw = meta.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        # Single tag as string
        tag = raw.strip().lower()
        return [tag] if tag else []
    if isinstance(raw, list):
        tags = []
        for item in raw:
            tag = str(item).strip().lower()
            if tag:
                tags.append(tag)
        return tags
    return []


def update_tags(path, tags):
    """Read file, update (or insert) the ``tags`` key in frontmatter, write back.

    Only the ``tags`` key changes, so comments and the order of the other keys
    survive. If no frontmatter exists, one is prepended. If *tags* is empty the
    ``tags`` key is removed.
    """
    try:
        note = read_note(path)
    except OSError:
        return

    text = note.text
    _meta, body = parse_frontmatter(text)
    if len(body) == len(text):
        block = _replace_tags("", tags)
        new_text = f"---\n{block}---\n{body}" if block else body
    else:
        m = _FRONTMATTER.match(text)
        block = _replace_tags(m.group(1), tags)
        new_text = text[:m.start(1)] + block + text[m.end(1):] if block.strip() else body

    save_note(path, new_text, note)


def _replace_tags(block, tags):
    """Swap the ``tags`` key in a YAML block, leaving every other line alone."""
    new = ""
    if tags:
        new = yaml.dump({"tags": sorted(tags)}, default_flow_style=False, allow_unicode=True)
    lines = block.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if _TAGS_KEY.match(line)), None)
    if start is None:
        return block + new
    end = start + 1
    # Its value runs on over indented lines, list items and a closing bracket
    while end < len(lines) and lines[end][:1] in (" ", "\t", "-", "]"):
        end += 1
    return "".join(lines[:start]) + new + "".join(lines[end:])
