# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Run from the repository root with: python3 -m unittest discover tests"""

import os
import stat
import tempfile
import unittest
from unittest import mock

from stenmark.frontmatter import update_tags
from stenmark.note_file import NoteChanged, read_note, save_note, write_atomic


class NoteFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.path = os.path.join(self.dir, "note.md")

    def write(self, data):
        with open(self.path, "wb") as f:
            f.write(data)

    def bytes(self):
        with open(self.path, "rb") as f:
            return f.read()

    def test_unchanged_text_is_not_written(self):
        self.write(b"a\n")
        note = read_note(self.path)
        os.utime(self.path, (1, 1))
        save_note(self.path, "a\n", note)
        self.assertEqual(os.stat(self.path).st_mtime, 1)

    def test_unchanged_text_never_touches_a_newer_version(self):
        self.write(b"old\n")
        note = read_note(self.path)
        self.write(b"synced\n")
        save_note(self.path, "old\n", note)
        self.assertEqual(self.bytes(), b"synced\n")

    def test_a_newer_version_is_not_overwritten(self):
        self.write(b"old\n")
        note = read_note(self.path)
        self.write(b"synced\n")
        with self.assertRaises(NoteChanged):
            save_note(self.path, "mine\n", note)
        self.assertEqual(self.bytes(), b"synced\n")

    def test_a_deleted_note_is_not_recreated(self):
        self.write(b"old\n")
        note = read_note(self.path)
        os.unlink(self.path)
        with self.assertRaises(NoteChanged):
            save_note(self.path, "mine\n", note)
        self.assertFalse(os.path.exists(self.path))

    def test_overwrite_replaces_a_newer_version(self):
        self.write(b"old\n")
        note = read_note(self.path)
        self.write(b"synced\n")
        save_note(self.path, "mine\n", note, overwrite=True)
        self.assertEqual(self.bytes(), b"mine\n")

    def test_successive_saves_track_their_own_writes(self):
        self.write(b"a\n")
        note = save_note(self.path, "b\n", read_note(self.path))
        save_note(self.path, "c\n", note)
        self.assertEqual(self.bytes(), b"c\n")

    def test_crlf_survives_a_save(self):
        self.write(b"a\r\nb\r\n")
        note = read_note(self.path)
        self.assertEqual(note.text, "a\nb\n")
        save_note(self.path, "a\nc\n", note)
        self.assertEqual(self.bytes(), b"a\r\nc\r\n")

    def test_latin1_opens_and_keeps_its_encoding(self):
        self.write(b"caf\xe9\n")
        note = read_note(self.path)
        self.assertEqual(note.text, "café\n")
        save_note(self.path, "thé\n", note)
        self.assertEqual(self.bytes(), b"th\xe9\n")

    def test_text_outside_the_encoding_leaves_the_file_alone(self):
        self.write(b"caf\xe9\n")
        with self.assertRaises(UnicodeEncodeError):
            save_note(self.path, "€\n", read_note(self.path))
        self.assertEqual(self.bytes(), b"caf\xe9\n")

    def test_failed_write_keeps_the_old_file_and_leaves_no_temp(self):
        self.write(b"old\n")
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_atomic(self.path, b"new\n")
        self.assertEqual(self.bytes(), b"old\n")
        self.assertEqual(os.listdir(self.dir), ["note.md"])

    def test_permissions_are_kept(self):
        self.write(b"a")
        os.chmod(self.path, 0o640)
        write_atomic(self.path, b"b")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)

    def test_a_read_only_note_is_refused(self):
        self.write(b"a")
        os.chmod(self.path, 0o440)
        with self.assertRaises(PermissionError):
            write_atomic(self.path, b"b")
        self.assertEqual(self.bytes(), b"a")

    def test_a_symlink_stays_a_symlink(self):
        self.write(b"a")
        link = os.path.join(self.dir, "link.md")
        os.symlink(self.path, link)
        write_atomic(link, b"b")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self.bytes(), b"b")

    def test_temporary_name_is_one_sync_clients_skip(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(os.path.basename(src))
            real_replace(src, dst)

        with mock.patch("os.replace", spy):
            write_atomic(self.path, b"a")
        self.assertTrue(seen[0].endswith("~"), seen)

    def test_tag_edit_keeps_line_endings_and_encoding(self):
        self.write(b"---\r\ntags: [a]\r\n---\r\ncaf\xe9\r\n")
        update_tags(self.path, ["b"])
        self.assertEqual(self.bytes(), b"---\r\ntags:\r\n- b\r\n---\r\ncaf\xe9\r\n")


if __name__ == "__main__":
    unittest.main()
