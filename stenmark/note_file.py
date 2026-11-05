# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""Reading and writing notes, shared by everything that touches one.

The notes are synced, so a save has to notice a version that arrived in the
meantime, and must never leave a half-written file for the sync client to
pick up.
"""

import dataclasses
import os
import re
import shutil
import tempfile


class NoteChanged(OSError):
    """The file on disk is no longer the one that was read, or is gone."""


@dataclasses.dataclass(frozen=True)
class Note:
    """A note as it was last read from, or written to, disk."""

    #: The content with LF line endings, which is also what the editor hands
    #: back whatever it was given.
    text: str
    #: The exact bytes on disk, to tell whether someone else has changed them.
    raw: bytes
    encoding: str
    newline: str


def valid_name(name):
    """Whether a typed name stays in its folder, rather than pointing elsewhere."""
    return "/" not in name and "\0" not in name and name not in (".", "..")


def note_filename(name):
    """A typed name as a note's filename: without .md the app can't list it."""
    return name if name.lower().endswith(".md") else name + ".md"


def moved_path(path, old, new):
    """Where `path` is now that `old` became `new`, whether itself or inside it."""
    if path == old:
        return new
    if path.startswith(old + os.sep):
        return new + path[len(old):]
    return path


def read_note(path):
    """Read a note, raising OSError if it can't be.

    Anything that isn't UTF-8 opens as Latin-1, which accepts every byte, so
    no note is unreadable and a save keeps the encoding it came in.

    A note mixing line endings gets its most common one on the next save.
    """
    with open(path, "rb") as f:
        raw = f.read()
    try:
        decoded, encoding = raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        decoded, encoding = raw.decode("latin-1"), "latin-1"
    crlf = raw.count(b"\r\n")
    newline = "\r\n" if crlf > raw.count(b"\n") - crlf else "\n"
    return Note(re.sub(r"\r\n?", "\n", decoded), raw, encoding, newline)


def save_note(path, text, base, overwrite=False):
    """Write `text` over the note read as `base`, returning the new state.

    Does nothing if the text is unchanged. Raises NoteChanged if the file is
    no longer `base`, unless `overwrite` says to replace it regardless.
    UnicodeEncodeError means the text doesn't fit the note's encoding.
    """
    if text == base.text and not overwrite:
        return base
    if not overwrite and _bytes_on_disk(path) != base.raw:
        raise NoteChanged(f"{path} changed on disk")
    raw = text.replace("\n", base.newline).encode(base.encoding)
    write_atomic(path, raw)
    return dataclasses.replace(base, text=text, raw=raw)


def _bytes_on_disk(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_atomic(path, data):
    """Replace the file at `path` with `data`, all at once or not at all.

    The temporary file has to sit beside the target for the rename to be
    atomic. Its name ends in ~ so that sync clients skip it: Nextcloud
    excludes *~ by default.
    """
    target = os.path.realpath(path)
    exists = os.path.exists(target)
    # A rename only needs a writable folder, so it would replace a read-only
    # file that an ordinary write refuses.
    if exists and not os.access(target, os.W_OK):
        raise PermissionError(13, os.strerror(13), path)
    fd, tmp = tempfile.mkstemp(
        prefix=".stenmark-", suffix="~", dir=os.path.dirname(target)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp's 0600 would otherwise replace the note's own permissions.
        if exists:
            shutil.copymode(target, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
