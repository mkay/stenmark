# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

from stenmark.frontmatter import parse_frontmatter

_TASK_MARKER = re.compile(r"\[([ xX])\](?=\s|$)")
_CODE_FORMATTER = HtmlFormatter(cssclass="highlight", wrapcode=True)
# Instead of markdown-it's own "replacements", which also turns two dots into
# an ellipsis, so a ../ path in running text would show as \u2026/.
_TYPOGRAPHY = (
    (re.compile(r"\.{3,}"), "\u2026"),
    (re.compile(r"(^|[^-])---(?=[^-]|$)", re.MULTILINE), "\\1\u2014"),
    (re.compile(r"(^|\s)--(?=\s|$)", re.MULTILINE), "\\1\u2013"),
    (re.compile(r"(^|[^-\s])--(?=[^-\s]|$)", re.MULTILINE), "\\1\u2013"),
)


def _typography(state):
    for token in state.tokens:
        if token.type != "inline":
            continue
        in_autolink = False
        for child in token.children:
            if child.type in ("link_open", "link_close") and child.markup == "autolink":
                in_autolink = child.type == "link_open"
            elif child.type == "text" and not in_autolink:
                for pattern, replacement in _TYPOGRAPHY:
                    child.content = pattern.sub(replacement, child.content)


def _source_lines(state):
    """Mark every block with its line in the file, for scroll sync and editing."""
    for token in state.tokens:
        if token.block and token.map and token.nesting >= 0 and token.type != "inline":
            token.attrSet("data-source-line", str(_file_line(state.env, token)))


def _task_items(state):
    """Turn `[ ]` at the start of a list item into a checkbox that knows its line."""
    tokens = state.tokens
    for item, paragraph, inline in zip(tokens, tokens[1:], tokens[2:]):
        if item.type != "list_item_open" or paragraph.type != "paragraph_open":
            continue
        first = inline.children[0] if inline.children else None
        marker = _TASK_MARKER.match(first.content) if first and first.type == "text" else None
        if not marker:
            continue
        item.attrSet("class", "task-item")
        first.content = first.content[marker.end():].lstrip()
        checkbox = Token("html_inline", "", 0)
        checked = " checked" if marker.group(1) != " " else ""
        checkbox.content = (
            f'<input type="checkbox"{checked} '
            f'data-source-line="{_file_line(state.env, paragraph)}"> '
        )
        inline.children.insert(0, checkbox)


def _file_line(env, token):
    return token.map[0] + 1 + env["frontmatter_lines"]


def _lexer_for(code, info):
    language = info.split(maxsplit=1)[0] if info.strip() else ""
    try:
        if language:
            return get_lexer_by_name(language, stripnl=False)
        return guess_lexer(code, stripnl=False)
    except ClassNotFound:
        return TextLexer(stripnl=False)


def _render_code(_renderer, tokens, idx, _options, _env):
    token = tokens[idx]
    html = highlight(token.content, _lexer_for(token.content, token.info), _CODE_FORMATTER)
    return html.replace(
        '<div class="highlight">',
        f'<div class="highlight" data-source-line="{token.attrGet("data-source-line")}">',
        1,
    )


class MarkdownRenderer:
    def __init__(self):
        self._md = MarkdownIt("commonmark", {"html": True, "typographer": True})
        self._md.enable(["table", "strikethrough", "smartquotes"])
        self._md.core.ruler.before("smartquotes", "typography", _typography)
        self._md.core.ruler.push("source_lines", _source_lines)
        self._md.core.ruler.push("task_items", _task_items)
        self._md.add_render_rule("fence", _render_code)
        self._md.add_render_rule("code_block", _render_code)

    @staticmethod
    def _split(text):
        """The note's body, and the env that maps its lines back onto the file."""
        _meta, body = parse_frontmatter(text)
        frontmatter = text[:len(text) - len(body)]
        return body, {"frontmatter_lines": frontmatter.count("\n")}

    def render(self, text):
        body, env = self._split(text)
        return self._md.render(body, env)

    def headings(self, text):
        """Return (level, title, line in the file) for every heading."""
        body, env = self._split(text)
        tokens = self._md.parse(body, env)
        return [
            (int(token.tag[1:]), _plain_text(inline), _file_line(env, token))
            for token, inline in zip(tokens, tokens[1:])
            if token.type == "heading_open"
        ]


def _plain_text(inline):
    return "".join(
        " " if child.type == "softbreak" else child.content
        for child in inline.children
        if child.type in ("text", "code_inline", "softbreak")
    )
