# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from stenmark.frontmatter import read_tags


class TagIndex:
    """In-memory index mapping tags to file paths and file paths to tags."""

    def __init__(self, root_directory):
        self._root = root_directory
        self._tag_to_files = {}   # tag -> set of paths
        self._file_to_tags = {}   # path -> list of tags
        self.rebuild()

    def rebuild(self):
        """Walk all .md files under root, rebuild the index from scratch."""
        self._tag_to_files.clear()
        self._file_to_tags.clear()
        self._walk(self._root)

    def _walk(self, directory):
        try:
            for entry in os.scandir(directory):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    self._walk(entry.path)
                elif entry.is_file() and entry.name.lower().endswith(".md"):
                    self._index_file(entry.path)
        except OSError:
            pass

    def _index_file(self, path):
        tags = read_tags(path)
        if tags:
            self._file_to_tags[path] = tags
            for tag in tags:
                self._tag_to_files.setdefault(tag, set()).add(path)

    def get_files(self, tag):
        """Return sorted list of file paths that have the given tag."""
        return sorted(self._tag_to_files.get(tag, set()))

    def get_tags(self, path):
        """Return list of tags for the given file path."""
        return self._file_to_tags.get(path, [])

    def all_tags(self):
        """Return sorted list of unique tags."""
        return sorted(self._tag_to_files.keys())

    def tag_count(self, tag):
        """Return the number of files with the given tag."""
        return len(self._tag_to_files.get(tag, set()))

    def update_file(self, path):
        """Re-index a single file (after edit/save)."""
        self.remove_file(path)
        if os.path.isfile(path):
            self._index_file(path)

    def remove_file(self, path):
        """Remove a file from the index."""
        old_tags = self._file_to_tags.pop(path, [])
        for tag in old_tags:
            files = self._tag_to_files.get(tag)
            if files:
                files.discard(path)
                if not files:
                    del self._tag_to_files[tag]

    def set_root(self, root_directory):
        """Change root directory and rebuild."""
        self._root = root_directory
        self.rebuild()
