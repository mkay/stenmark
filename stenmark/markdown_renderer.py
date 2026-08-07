# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import markdown
from markdown.treeprocessors import Treeprocessor


class _SourceLineProcessor(Treeprocessor):
    """Inject data-source-line attributes on block elements by matching content to source lines."""

    def run(self, root):
        source = self.md._source_lines
        if not source:
            return
        # Build index: stripped line text -> first occurrence line number
        line_index = {}
        for i, line in enumerate(source, 1):
            stripped = line.strip()
            if stripped and stripped not in line_index:
                line_index[stripped] = i

        self._annotate(root, line_index, source)

    def _annotate(self, element, line_index, source):
        for child in element:
            tag = child.tag
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = (child.text or "").strip()
                if text:
                    for i, line in enumerate(source, 1):
                        s = line.strip().lstrip("#").strip()
                        if s == text:
                            child.set("data-source-line", str(i))
                            break
            elif tag in ("p", "table", "pre", "div"):
                text = (child.text or "").strip()
                if text:
                    first_line = text.split("\n")[0].strip()
                    if first_line in line_index:
                        child.set("data-source-line", str(line_index[first_line]))
            elif tag in ("ul", "ol"):
                # Annotate the list itself with the line of its first item
                first_li = child.find("li")
                if first_li is not None:
                    li_text = (first_li.text or "").strip()
                    if li_text:
                        # Strip list markers from source to match
                        bare = li_text.split("\n")[0].strip()
                        for i, line in enumerate(source, 1):
                            s = re.sub(r"^\s*[-*+]\s+(\[[ xX]\]\s+)?|^\s*\d+\.\s+", "", line).strip()
                            if s == bare:
                                child.set("data-source-line", str(i))
                                break
            elif tag == "blockquote":
                bq_text = (child.text or "")
                p = child.find("p")
                if p is not None:
                    bq_text = (p.text or "")
                first_line = bq_text.strip().split("\n")[0].strip()
                if first_line:
                    for i, line in enumerate(source, 1):
                        s = line.strip().lstrip(">").strip()
                        if s == first_line:
                            child.set("data-source-line", str(i))
                            break


class _SourceLineExtension(markdown.Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(
            _SourceLineProcessor(md), "source_lines", 1
        )


class MarkdownRenderer:
    def __init__(self):
        self._extensions = [
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
            "smarty",
            "attr_list",
            "md_in_html",
            _SourceLineExtension(),
        ]
        self._extension_configs = {
            "codehilite": {
                "css_class": "highlight",
                "guess_lang": True,
            },
        }

    def render(self, text):
        from stenmark.frontmatter import parse_frontmatter
        _meta, text = parse_frontmatter(text)
        md = markdown.Markdown(
            extensions=self._extensions,
            extension_configs=self._extension_configs,
            tab_length=2,
        )
        md._source_lines = text.splitlines()
        html = md.convert(text)
        # Convert task-list items: <li>[ ] ... and <li>[x] ...
        html = re.sub(
            r"<li>\[ \]",
            '<li class="task-item"><input type="checkbox"> ',
            html,
        )
        html = re.sub(
            r"<li>\[[xX]\]",
            '<li class="task-item"><input type="checkbox" checked> ',
            html,
        )
        return html
