# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import re

import yaml


def parse_frontmatter(text):
    """Return (metadata_dict, body_without_frontmatter).

    If no valid frontmatter, returns ({}, original_text).
    Frontmatter = text between opening ``---\\n`` and closing ``---\\n``
    at the very start of the file.
    """
    if not text.startswith("---"):
        return {}, text

    # Match opening --- (with optional trailing whitespace) then content then closing ---
    m = re.match(r"^---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?\n", text, re.DOTALL)
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

    Preserves all other frontmatter keys. If no frontmatter exists, one is
    prepended. If *tags* is empty the ``tags`` key is removed.
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return

    meta, body = parse_frontmatter(text)

    if tags:
        meta["tags"] = sorted(tags)
    else:
        meta.pop("tags", None)

    if meta:
        fm_str = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=True)
        new_text = f"---\n{fm_str}---\n{body}"
    else:
        new_text = body

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
