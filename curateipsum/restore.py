"""
Module for restoring a backed-up snapshot (or a subset of its paths) to a
destination directory.
"""
import logging
import os
from typing import Iterable, List, Optional, Tuple, Union

from curateipsum import backup, fs

_lg = logging.getLogger(__name__)

OVERWRITE_NEVER = "never"
OVERWRITE_ALWAYS = "always"
OVERWRITE_POLICIES = (OVERWRITE_NEVER, OVERWRITE_ALWAYS)

# Snapshot-root entries that are backup bookkeeping, not backed-up data,
# and must never be copied out during a restore.
_SNAPSHOT_INTERNAL_PREFIXES = (backup.BACKUP_MARKER, backup.DELTA_DIR)


class RestoreError(Exception):
    """Raised when a restore could not be completed safely or fully."""


def _is_snapshot_internal(top_name: str) -> bool:
    return any(top_name.startswith(p) for p in _SNAPSHOT_INTERNAL_PREFIXES)


def _under_any(relpath: str, rel_paths: List[str]) -> bool:
    return any(relpath == p or relpath.startswith(p + os.sep)
              for p in rel_paths)


def plan_restore(
    snapshot_entry: Union[os.DirEntry, fs.PseudoDirEntry],
    rel_paths: Optional[List[str]] = None,
) -> Iterable[Tuple[Union[os.DirEntry, fs.PseudoDirEntry], str]]:
    """
    Yield (entry, relpath) pairs a restore would copy, directories before
    their contents (fs.scantree's default order, which copy_direntry()
    depends on so a directory exists before anything is written into it).
    Skips snapshot-internal bookkeeping entries (backup marker, delta
    dir). If rel_paths is given, only entries at or under one of those
    snapshot-relative paths are included.

    A generator rather than a list: fs.scantree() already streams, and a
    snapshot can hold far more entries than comfortably fit in memory at
    once.
    """
    for entry in fs.scantree(snapshot_entry.path):
        relpath = os.path.relpath(entry.path, snapshot_entry.path)
        top_name = relpath.split(os.sep, 1)[0]
        if _is_snapshot_internal(top_name):
            continue
        if rel_paths is not None and not _under_any(relpath, rel_paths):
            continue
        yield entry, relpath


def restore_snapshot(
    snapshot_entry: Union[os.DirEntry, fs.PseudoDirEntry],
    dest_dir: str,
    dry_run: bool = False,
    overwrite: str = OVERWRITE_NEVER,
    rel_paths: Optional[List[str]] = None,
) -> List[str]:
    """
    Restore a completed snapshot (or a subset of its paths) into dest_dir.

    :param overwrite: "never" (default) leaves any destination path that
        already exists untouched and reports it as skipped; "always"
        removes and replaces it.
    :param rel_paths: restrict the restore to these snapshot-relative
        paths (and anything nested under them); default restores
        everything in the snapshot.
    :return: relative paths that already existed at dest_dir under
        overwrite="never" - skipped for real, or (on dry_run) reported as
        what would be skipped.
    :raises RestoreError: if the snapshot has no manifest, dest_dir is
        inside the snapshot being restored, a destination path would
        resolve outside dest_dir (e.g. via a symlinked parent directory),
        or a copy fails partway through (the destination is left as-is;
        already-restored paths are not rolled back).
    """
    if overwrite not in OVERWRITE_POLICIES:
        raise ValueError("Unknown overwrite policy: %r" % overwrite)

    manifest = backup._read_manifest(
        backup._get_backup_marker(snapshot_entry).path)
    # A pre-migration (_LEGACY_MANIFEST) marker carries no checksums or
    # excluded-entries record, but the snapshot data itself is still
    # restorable - only verify_restored() needs real manifest content.
    if manifest is None:
        raise RestoreError(
            "Cannot restore %s: missing or corrupt manifest"
            % snapshot_entry.name
        )

    dest_canon = backup._canonical(dest_dir)
    snapshot_canon = backup._canonical(snapshot_entry.path)
    if backup._is_same_or_within(dest_canon, snapshot_canon):
        raise RestoreError(
            "Refusing to restore %s into itself (destination %s is inside "
            "the snapshot)" % (snapshot_entry.name, dest_dir)
        )

    skipped = []
    for entry, relpath in plan_restore(snapshot_entry, rel_paths):
        dst_path = os.path.join(dest_dir, relpath)
        # A symlink planted under dest_dir (by another process, or left
        # over from a previous run) could otherwise redirect lexists(),
        # rm_direntry(), or copy_direntry() below to write, delete, or
        # read through it, outside dest_dir entirely.
        dst_canon = backup._canonical(dst_path)
        if not backup._is_same_or_within(dst_canon, dest_canon):
            raise RestoreError(
                "Refusing to restore %s: resolves outside destination "
                "%s (a parent path component may be a symlink)"
                % (relpath, dest_dir)
            )
        exists = os.path.lexists(dst_path)
        if exists and overwrite == OVERWRITE_NEVER:
            _lg.info("Skipping existing %s (overwrite=%s)",
                     relpath, OVERWRITE_NEVER)
            skipped.append(relpath)
            continue
        if dry_run:
            _lg.info("Would restore %s -> %s", relpath, dst_path)
            continue
        if exists:
            fs.rm_direntry(fs.PseudoDirEntry(dst_path))
        parent = os.path.dirname(dst_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        try:
            fs.copy_direntry(entry, dst_path)
        except (OSError, fs.BackupCreationError) as err:
            raise RestoreError(
                "Failed to restore %s: %s" % (relpath, err)
            ) from err

    return skipped


def verify_restored(
    snapshot_entry: Union[os.DirEntry, fs.PseudoDirEntry],
    dest_dir: str,
    rel_paths: Optional[List[str]] = None,
) -> List[str]:
    """
    Verify restored file content at dest_dir against the checksums the
    snapshot's manifest recorded at backup time. Mirrors
    backup.verify_snapshot(), but against an arbitrary restore
    destination rather than the snapshot directory itself.

    :return: relative paths whose restored content doesn't match the
        recorded checksum, or is missing. Empty means verified OK.
    :raises RestoreError: if the manifest itself is missing or corrupt.
    """
    manifest = backup._read_manifest(
        backup._get_backup_marker(snapshot_entry).path)
    if manifest is None or manifest is backup._LEGACY_MANIFEST:
        raise RestoreError(
            "Cannot verify %s: missing, corrupt, or pre-migration manifest"
            % snapshot_entry.name
        )

    dest_canon = backup._canonical(dest_dir)
    mismatches = []
    for relpath, expected_digest in manifest.get("checksums", {}).items():
        if rel_paths is not None and not _under_any(relpath, rel_paths):
            continue
        full_path = os.path.join(dest_dir, relpath)
        # Same symlink-escape concern as restore_snapshot(): don't let a
        # planted symlink under dest_dir make this hash a file outside it.
        full_canon = backup._canonical(full_path)
        if not backup._is_same_or_within(full_canon, dest_canon):
            _lg.error("Refusing to verify %s: resolves outside "
                     "destination %s", relpath, dest_dir)
            mismatches.append(relpath)
            continue
        try:
            actual_digest = backup._sha256_file(full_path)
        except OSError:
            mismatches.append(relpath)
            continue
        if actual_digest != expected_digest:
            mismatches.append(relpath)
    return mismatches
