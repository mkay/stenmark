# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from stenmark import settings_manager
from stenmark.frontmatter import read_tags, update_tags
from stenmark.note_file import moved_path, note_filename, valid_name
from stenmark.search_panel import SearchPanel


class TagEditTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "note.md")

    def edit(self, text, tags):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        update_tags(self.path, tags)
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def test_comments_and_key_order_survive(self):
        text = "---\n# why\nzebra: 1\ntags: [a]\napple: 2\n---\nbody\n"
        self.assertEqual(
            self.edit(text, ["b"]),
            "---\n# why\nzebra: 1\ntags:\n- b\napple: 2\n---\nbody\n",
        )

    def test_block_and_indented_lists_are_replaced_whole(self):
        for old in ("tags:\n- a\n- b\n", "tags:\n  - a\n  - b\n", "tags: [a,\n  b\n]\n"):
            self.assertEqual(
                self.edit(f"---\n{old}after: 1\n---\n", ["c"]),
                "---\ntags:\n- c\nafter: 1\n---\n",
            )

    def test_a_key_that_merely_starts_with_tags_is_left_alone(self):
        self.assertEqual(
            self.edit("---\ntagsline: x\n---\n", ["c"]),
            "---\ntagsline: x\ntags:\n- c\n---\n",
        )

    def test_tags_are_added_to_frontmatter_without_any(self):
        self.assertEqual(self.edit("---\na: 1\n---\nb\n", ["x"]), "---\na: 1\ntags:\n- x\n---\nb\n")

    def test_frontmatter_is_created_when_missing(self):
        self.assertEqual(self.edit("body\n", ["x"]), "---\ntags:\n- x\n---\nbody\n")

    def test_removing_the_last_tag_drops_an_empty_block(self):
        self.assertEqual(self.edit("---\ntags: [a]\n---\nbody\n", []), "body\n")

    def test_removing_tags_keeps_the_rest(self):
        self.assertEqual(self.edit("---\ntags: [a]\na: 1\n---\nb\n", []), "---\na: 1\n---\nb\n")

    def test_a_tag_yaml_would_misread_round_trips(self):
        self.edit("body\n", ["a: b", "yes"])
        self.assertEqual(sorted(read_tags(self.path)), ["a: b", "yes"])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = pathlib.Path(tmp.name) / "settings.json"
        for name, value in (("CONFIG_DIR", self.file.parent), ("CONFIG_FILE", self.file)):
            patcher = mock.patch.object(settings_manager, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_damaged_file_is_not_overwritten(self):
        for damaged in ('{"pinned_files": [', "[1, 2]"):
            self.file.write_text(damaged)
            settings = settings_manager.SettingsManager()
            self.assertTrue(settings.load_failed)
            settings.set("font_size", 20)
            self.assertEqual(settings.get("font_size"), 20)
            self.assertEqual(self.file.read_text(), damaged)

    def test_missing_file_is_not_damage(self):
        settings = settings_manager.SettingsManager()
        self.assertFalse(settings.load_failed)
        settings.set("font_size", 20)
        self.assertEqual(json.loads(self.file.read_text())["font_size"], 20)

    def test_unknown_keys_survive_a_save(self):
        self.file.write_text('{"from_the_future": 1}')
        settings_manager.SettingsManager().set("font_size", 20)
        self.assertEqual(json.loads(self.file.read_text())["from_the_future"], 1)

    def test_pins_move_with_a_folder_but_not_a_lookalike(self):
        self.file.write_text(json.dumps({
            "pinned_files": ["/n/a/x.md", "/n/ab/y.md"],
            "pinned_folders": ["/n/a", "/n/a/sub"],
        }))
        settings = settings_manager.SettingsManager()
        settings.move_pins("/n/a", "/n/b")
        self.assertEqual(settings.pinned_files, ["/n/b/x.md", "/n/ab/y.md"])
        self.assertEqual(settings.pinned_folders, ["/n/b", "/n/b/sub"])


class NamesTest(unittest.TestCase):
    def test_valid_name(self):
        for name in ("a", "a.md", "a b", "..a"):
            self.assertTrue(valid_name(name), name)
        for name in ("a/b", "../x", "/x", ".", "..", "a\0b"):
            self.assertFalse(valid_name(name), name)

    def test_note_filename(self):
        self.assertEqual(note_filename("a"), "a.md")
        self.assertEqual(note_filename("a.MD"), "a.MD")

    def test_moved_path(self):
        self.assertEqual(moved_path("/a", "/a", "/b"), "/b")
        self.assertEqual(moved_path("/a/x", "/a", "/b"), "/b/x")
        self.assertEqual(moved_path("/ab", "/a", "/b"), "/ab")


class SnippetTest(unittest.TestCase):
    def test_context_is_kept_on_both_sides(self):
        content = " ".join(f"word{i}" for i in range(40))
        pos = content.index("word20")
        snippet = SearchPanel._build_snippet(content, pos, len("word20"))
        self.assertIn("word13 ", snippet)
        self.assertIn(" word27", snippet)
        self.assertIn("<b>word20</b>", snippet)

    def test_cut_falls_on_word_boundaries(self):
        content = " ".join(f"word{i}" for i in range(40))
        pos = content.index("word20")
        before = SearchPanel._build_snippet(content, pos, 6).split("<b>")[0]
        self.assertTrue(before.startswith("…word"), before)


if __name__ == "__main__":
    unittest.main()
