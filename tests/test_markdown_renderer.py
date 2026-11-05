# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import re
import unittest

from stenmark.markdown_renderer import MarkdownRenderer


class RendererTest(unittest.TestCase):
    def setUp(self):
        self.renderer = MarkdownRenderer()

    def render(self, text):
        return self.renderer.render(text)

    def lines_of(self, html, tag):
        return re.findall(rf'<{tag}\b[^>]*data-source-line="(\d+)"', html)

    def test_source_lines_count_the_frontmatter(self):
        html = self.render("---\ntags: [a]\n---\n\n\n# Title\n")
        self.assertEqual(self.lines_of(html, "h1"), ["6"])

    def test_repeated_headings_keep_their_own_lines(self):
        html = self.render("## Notes\n\na\n\n## Notes\n")
        self.assertEqual(self.lines_of(html, "h2"), ["1", "5"])

    def test_heading_with_inline_markup_has_a_line(self):
        self.assertEqual(self.lines_of(self.render("# Foo **bar**\n"), "h1"), ["1"])

    def test_code_block_has_a_line(self):
        html = self.render("para\n\n```python\nx = 1\n```\n")
        self.assertIn('<div class="highlight" data-source-line="3">', html)

    def test_checkbox_knows_its_line_past_a_fenced_example(self):
        html = self.render("```\n- [ ] example\n```\n\n- [ ] real\n")
        self.assertEqual(self.lines_of(html, "input"), ["5"])

    def test_checkbox_states(self):
        html = self.render("- [ ] a\n- [x] b\n- [X] c\n")
        self.assertEqual(html.count("<input"), 3)
        self.assertEqual(html.count(" checked"), 2)
        self.assertEqual(html.count('class="task-item"'), 3)
        self.assertNotIn("[", html)

    def test_numbered_and_loose_tasks_get_checkboxes(self):
        self.assertIn("<input", self.render("1. [ ] a\n"))
        self.assertEqual(self.render("- [ ] a\n\n- [x] b\n").count("<input"), 2)

    def test_brackets_without_a_gap_are_not_a_task(self):
        self.assertNotIn("<input", self.render("- [x]y\n"))

    def test_strikethrough(self):
        self.assertIn("<s>x</s>", self.render("~~x~~\n"))

    def test_fence_inside_a_list(self):
        html = self.render("- a\n\n  ```python\n  x = 1\n  ```\n")
        self.assertIn('<div class="highlight"', html)

    def test_list_straight_after_a_paragraph(self):
        self.assertIn("<ul", self.render("Shopping:\n- milk\n"))

    def test_numbered_list_keeps_its_start(self):
        self.assertIn('start="3"', self.render("3. a\n4. b\n"))

    def test_markdown_inside_details(self):
        self.assertIn("<em>hi</em>", self.render("<details>\n\n*hi*\n\n</details>\n"))

    def test_shebang_is_not_a_heading(self):
        self.assertNotIn("<h1", self.render("#!/bin/sh\n"))

    def test_unknown_language_still_renders(self):
        self.assertIn("x = 1", self.render("```nosuchlanguage\nx = 1\n```\n"))

    def test_blank_lines_in_code_survive(self):
        html = self.render("```text\n\na\n\nb\n```\n")
        self.assertIn("<code>\na\n\nb\n</code>", html)

    def test_headings_match_the_page(self):
        text = "---\na: 1\n---\nTitle\n=====\n\n#NoSpace\n\n## Foo **bar** `x`\n\n```\n# not one\n```\n\n> ### Quoted\n"
        self.assertEqual(
            self.renderer.headings(text),
            [(1, "Title", 4), (2, "Foo bar x", 9), (3, "Quoted", 15)],
        )
        self.assertEqual(len(re.findall(r"<h[1-6]\b", self.render(text))), 3)


if __name__ == "__main__":
    unittest.main()
