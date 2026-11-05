# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import base64
import hashlib
import re
import unittest

from stenmark.html_template import wrap_html


class PagePolicyTest(unittest.TestCase):
    def test_policy_comes_before_the_note(self):
        html = wrap_html("<p>NOTE</p>")
        self.assertLess(html.index("Content-Security-Policy"), html.index("NOTE"))

    def test_policy_allows_exactly_the_app_script(self):
        html = wrap_html("<p>note</p>", read_only_tasks=True)
        scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        self.assertEqual(len(scripts), 1)
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
        self.assertIn(f"script-src 'sha256-{digest}'", html)

    def test_policy_has_no_inline_or_remote_script_escape(self):
        policy = re.search(r'Content-Security-Policy" content="([^"]*)"', wrap_html("")).group(1)
        script_src = re.search(r"script-src ([^;]*)", policy).group(1)
        self.assertNotIn("unsafe", script_src)
        self.assertNotIn("http", policy)
        self.assertIn("default-src 'none'", policy)


if __name__ == "__main__":
    unittest.main()
