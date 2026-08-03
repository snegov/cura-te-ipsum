"""
Module with backup functions.
"""
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Iterable, Union

try:
    import fcntl
except ImportError:
    # Not available on Windows. cli.py's own platform check reports this
    # cleanly before any locking function here is ever called; importing
    # fcntl lazily/optionally lets that check run instead of crashing at
    # `from curateipsum import backup` time.
    fcntl = None

from curateipsum import fs

BACKUP_ENT_FMT = "%Y%m%d_%H%M%S"
LOCK_FILE = ".backups_lock"
DELTA_DIR = ".backup_delta"
BACKUP_MARKER = ".backup_finished"
STAGING_PREFIX = ".incomplete-"
REPO_ID_FILE = ".curateipsum_repo_id"
_lg = logging.getLogger(__name__)


class BackupFailedError(Exception):
    """Raised when a backup could not be completed successfully.

    Any failure while building a snapshot (copy error, parse error,
    unsupported entry, nonzero subprocess exit) is fatal: the partially
    built snapshot is discarded and this is the only way that failure is
    reported to callers. Topology validation and destructive-path
    boundary failures also raise this, since both mean the run cannot
    proceed safely.
    """


def _canonical(path: str) -> str:
    """Absolute, symlink-resolved path used for boundary comparisons."""
    return os.path.realpath(os.path.abspath(path))


def _is_same_or_within(inner: str, outer: str) -> bool:
    """
    True if canonical path `inner` equals or is nested under `outer`.
    commonpath() compares path components, not raw string prefixes, so
    this is correct even when `outer` is the filesystem root - unlike a
    startswith(outer + sep) check, which mishandles root.
    """
    return os.path.commonpath([inner, outer]) == outer


def validate_topology(sources: List[str], backups_dir_abs: str) -> None:
    """
    Reject a source/backups_dir layout that could lead to a source being
    backed up into itself, a backup silently overwriting another source,
    or two sources colliding at the same destination path.

    :raises BackupFailedError: if any boundary or collision check fails.
    """
    backups_canon = _canonical(backups_dir_abs)

    seen_canon: Dict[str, str] = {}
    seen_basename: Dict[str, str] = {}
    for src in sources:
        src_canon = _canonical(src)

        if _is_same_or_within(src_canon, backups_canon):
            raise BackupFailedError(
                "Source %s is inside the backups directory %s"
                % (src, backups_dir_abs)
            )
        if _is_same_or_within(backups_canon, src_canon):
            raise BackupFailedError(
                "Backups directory %s is inside source %s"
                % (backups_dir_abs, src)
            )

        if src_canon in seen_canon:
            raise BackupFailedError(
                "Duplicate source: %s and %s both resolve to %s"
                % (seen_canon[src_canon], src, src_canon)
            )
        seen_canon[src_canon] = src

        basename = os.path.basename(src_canon)
        if basename in seen_basename:
            raise BackupFailedError(
                "Sources %s and %s both back up to the same destination "
                "name %r; use distinct directory names"
                % (seen_basename[basename], src, basename)
            )
        seen_basename[basename] = src


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _read_small_file_no_follow(path: str, max_bytes: int = 4096
                               ) -> Optional[str]:
    """
    Read a small file, refusing to follow a symlink at `path`. Returns
    None if the path doesn't exist, isn't a regular file, or is a
    symlink.
    """
    try:
        fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    except OSError:
        return None
    try:
        return os.read(fd, max_bytes).decode()
    finally:
        os.close(fd)


def _write_small_file_no_follow(path: str, content: str):
    """
    Atomically (create-or-replace) write a small file at `path`. Writes
    to a sibling temp file and renames it into place: rename() replaces
    whatever directory entry currently sits at `path` - including a
    symlink itself, never the symlink's target - so this can never write
    through a pre-existing symlink. It also means a concurrent reader
    never observes a partially-written or stale-plus-new-content file.
    """
    tmp_path = "%s.tmp-%d" % (path, os.getpid())
    fd = os.open(tmp_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW, 0o644)
    try:
        os.write(fd, content.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, path)


def _ensure_repo_id(backups_dir: str) -> str:
    """
    Return this backups directory's identity, generating and persisting
    one on first use. Recorded in every snapshot's manifest so a deletion
    can later verify a directory genuinely belongs to this repository
    before it is recursively removed.
    """
    id_path = os.path.join(backups_dir, REPO_ID_FILE)
    repo_id = _read_small_file_no_follow(id_path)
    if repo_id:
        return repo_id.strip()

    repo_id = uuid.uuid4().hex
    _write_small_file_no_follow(id_path, repo_id)
    return repo_id


def _write_manifest(marker_path: str, backups_dir: str, snapshot_name: str):
    """Write and fsync the completion manifest for a finished snapshot."""
    manifest = json.dumps({
        "repo_id": _ensure_repo_id(backups_dir),
        "snapshot": snapshot_name,
    })
    _write_small_file_no_follow(marker_path, manifest)


# Sentinel for a marker that exists but predates the JSON manifest
# format (an empty touch file, as set_backup_marker() used to write).
# Distinguished from corrupt/forged content: an empty marker can only
# be a pre-migration artifact, never a deliberately altered one.
_LEGACY_MANIFEST = object()


def _read_manifest(marker_path: str) -> Union[dict, object, None]:
    """
    Read a snapshot manifest. Returns _LEGACY_MANIFEST for a pre-migration
    empty marker, or None if the marker is missing, unreadable, or holds
    content that fails to parse as JSON (corrupt or forged).
    """
    try:
        with open(marker_path, "r") as f:
            content = f.read()
    except OSError:
        return None
    if not content:
        return _LEGACY_MANIFEST
    try:
        return json.loads(content)
    except ValueError:
        return None


def _verify_safe_to_delete(entry: os.DirEntry, backups_dir_abs: str,
                           repo_id: str) -> bool:
    """
    Verify a snapshot directory entry may be recursively deleted: it must
    be a real, non-symlinked directory living directly inside
    backups_dir_abs, on the same filesystem (never crossing a mount
    point), and carrying a manifest whose repo_id matches this
    repository's identity.
    """
    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
        _lg.error("Refusing to delete %s: not a real directory", entry.path)
        return False

    entry_canon = _canonical(entry.path)
    if os.path.dirname(entry_canon) != backups_dir_abs:
        _lg.error("Refusing to delete %s: escapes backups directory %s",
                  entry.path, backups_dir_abs)
        return False

    try:
        entry_dev = os.stat(entry.path).st_dev
        backups_dev = os.stat(backups_dir_abs).st_dev
    except OSError as err:
        _lg.error("Refusing to delete %s: stat failed: %s", entry.path, err)
        return False
    if entry_dev != backups_dev:
        _lg.error("Refusing to delete %s: crosses a mount point",
                  entry.path)
        return False

    manifest = _read_manifest(_get_backup_marker(entry).path)
    if manifest is _LEGACY_MANIFEST:
        _lg.warning(
            "%s has a pre-migration marker with no repository identity; "
            "adopting it into repository %s", entry.path, repo_id
        )
        return True
    if manifest is None or manifest.get("repo_id") != repo_id:
        _lg.error(
            "Refusing to delete %s: missing, corrupt, or mismatched "
            "repository identity in manifest", entry.path
        )
        return False

    return True


def _get_backup_marker(
        backup_entry: Union[os.DirEntry, fs.PseudoDirEntry]
) -> fs.PseudoDirEntry:
    """Return DirEntry for marker file of given backup."""
    marker_name = "%s_%s" % (BACKUP_MARKER, backup_entry.name)
    marker_path = os.path.join(backup_entry.path, marker_name)
    return fs.PseudoDirEntry(path=marker_path)


def _is_backup(backup_entry: Union[os.DirEntry, fs.PseudoDirEntry]) -> bool:
    """Guess if backup_entry is a real backup."""
    backup_marker = _get_backup_marker(backup_entry)
    # if there is no marker file in the backup dir, it's not a backup
    if not os.path.exists(backup_marker.path):
        return False
    # if there is only a marker file in the backup dir, it's not a backup
    if os.listdir(backup_entry.path) == [backup_marker.name]:
        return False
    try:
        datetime.strptime(backup_entry.name, BACKUP_ENT_FMT)
        return True
    except ValueError:
        return False


def _iterate_backups(backups_dir: str) -> Iterable[os.DirEntry]:
    """Iterate over backups in backups_dir."""
    b_iter = os.scandir(backups_dir)

    b_ent: os.DirEntry
    for b_ent in b_iter:
        if not _is_backup(b_ent):
            continue
        yield b_ent

    b_iter.close()


def _get_latest_backup(backups_dir: str) -> Optional[os.DirEntry]:
    """Returns path to latest backup created in backups_dir or None."""
    all_backups = sorted(_iterate_backups(backups_dir), key=lambda e: e.name)
    if all_backups:
        return all_backups[-1]
    return None


def _date_from_backup(backup_entry: os.DirEntry) -> datetime:
    """Returns datetime object from backup name."""
    return datetime.strptime(backup_entry.name, BACKUP_ENT_FMT)


# Open lock file descriptors currently held by this process, keyed by the
# absolute path of the backups directory they lock. The kernel associates
# an flock() with this exact open file description, so the descriptor must
# stay open for the full duration of the operation: closing it (including
# on process crash or signal) is what releases the lock.
_held_locks: Dict[str, int] = {}


_LOCK_METADATA_MAX_BYTES = 256


def _read_lock_metadata(lock_file_path: str) -> str:
    """
    Read lock file content for diagnostic logging only. Never raises, and
    never trusted for anything beyond a human-readable log line: the read
    is capped and newlines are stripped so a stale or forged lock file
    can't inject bogus log lines or force an unbounded read.
    """
    try:
        with open(lock_file_path, "r") as f:
            content = f.read(_LOCK_METADATA_MAX_BYTES)
    except OSError:
        return "<unreadable>"
    return content.replace("\n", " ").replace("\r", " ").strip()


def set_backups_lock(backups_dir: str,
                     force: bool = False) -> bool:
    """
    Acquire an exclusive kernel (flock) lock to prevent multiple backups
    running at the same time. The lock file also holds the PID and start
    time of the holder, kept for diagnostics only - they play no part in
    deciding whether the lock can be acquired.

    If another process already holds the lock:
    - with force=False, return False immediately.
    - with force=True, block until that process releases it (normal exit,
      signal, or crash all release the kernel lock), then acquire it.
    """
    backups_dir_abs = os.path.abspath(backups_dir)
    if backups_dir_abs in _held_locks:
        _lg.error("This process already holds the backup lock for %s",
                  backups_dir)
        return False

    lock_file_path = os.path.join(backups_dir_abs, LOCK_FILE)

    fd = os.open(lock_file_path, os.O_CREAT | os.O_RDWR, 0o644)

    flock_flags = fcntl.LOCK_EX if force else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flock_flags)
    except BlockingIOError:
        held_by = _read_lock_metadata(lock_file_path)
        _lg.warning(
            "Previous backup is still in progress (%s), exiting", held_by
        )
        os.close(fd)
        return False
    except OSError as err:
        _lg.error("Failed to acquire backup lock: %s", err)
        os.close(fd)
        return False

    # Lock acquired: replace metadata, it belongs to us now. If writing it
    # fails, don't leave the lock held forever - release and report failure.
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        metadata = "%d\n%s\n" % (os.getpid(), datetime.now().isoformat())
        os.write(fd, metadata.encode())
        os.fsync(fd)
    except OSError as err:
        _lg.error("Failed to write backup lock metadata: %s", err)
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        return False

    _held_locks[backups_dir_abs] = fd
    return True


def release_backups_lock(backups_dir: str):
    """
    Release the kernel lock held by this process for backups_dir, if any.
    Only releases a lock this process actually acquired via
    set_backups_lock() - verified by looking up our own held descriptor,
    never by trusting the lock file's on-disk content.
    """
    backups_dir_abs = os.path.abspath(backups_dir)
    fd = _held_locks.pop(backups_dir_abs, None)
    if fd is None:
        _lg.debug("No lock held by this process for %s, nothing to release",
                  backups_dir)
        return

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    # Deliberately not unlinking the lock file: flock() locks an inode, not
    # a path. Unlinking it here while another process is blocked opening
    # the same path (force=True) would let that process (or a third one)
    # create a fresh inode at the same path and acquire an independent
    # lock, defeating mutual exclusion. The file is small and harmless to
    # leave in place; only its content (diagnostics) gets overwritten by
    # whoever next holds the lock.


def set_backup_marker(backup_entry: Union[os.DirEntry, fs.PseudoDirEntry]):
    """Create finished backup marker file in backup's directory."""
    backup_marker = _get_backup_marker(backup_entry)
    if not os.path.exists(backup_marker.path):
        backups_dir = os.path.dirname(os.path.normpath(backup_entry.path))
        _write_manifest(backup_marker.path, backups_dir, backup_entry.name)


_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _fsync_dir(path: str):
    """Fsync a directory so its content is durable before it is renamed."""
    dir_fd = os.open(path, os.O_RDONLY | _O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _reserve_snapshot_name(backups_dir: str) -> str:
    """
    Return a snapshot name that doesn't collide with an existing entry or
    an in-progress staging directory. Guards against two backups started
    within the same second.
    """
    def _taken(candidate: str) -> bool:
        return (os.path.lexists(os.path.join(backups_dir, candidate))
                or os.path.lexists(os.path.join(
                    backups_dir, f"{STAGING_PREFIX}{candidate}")))

    name = datetime.now().strftime(BACKUP_ENT_FMT)
    while _taken(name):
        time.sleep(1)
        name = datetime.now().strftime(BACKUP_ENT_FMT)
    return name


def cleanup_stale_staging_dirs(backups_dir: str):
    """
    Remove staging directories abandoned by a crashed or interrupted
    backup run. Must be called before a new backup starts so a stale
    staging directory can never be mistaken for a real snapshot.
    """
    backups_dir_abs = _canonical(backups_dir)
    try:
        backups_dev = os.stat(backups_dir_abs).st_dev
    except OSError as err:
        _lg.error("Cannot stat backups directory %s: %s", backups_dir, err)
        return

    with os.scandir(backups_dir) as it:
        entry: os.DirEntry
        for entry in it:
            if not entry.name.startswith(STAGING_PREFIX):
                continue
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                _lg.error("Refusing to remove %s: not a real directory",
                          entry.path)
                continue
            if os.path.dirname(_canonical(entry.path)) != backups_dir_abs:
                _lg.error("Refusing to remove %s: escapes backups directory",
                          entry.path)
                continue
            try:
                if os.stat(entry.path).st_dev != backups_dev:
                    _lg.error("Refusing to remove %s: crosses a mount point",
                              entry.path)
                    continue
            except OSError as err:
                _lg.error("Cannot stat %s: %s", entry.path, err)
                continue
            _lg.warning("Removing abandoned staging directory: %s",
                       entry.name)
            shutil.rmtree(entry.path, ignore_errors=True)


def cleanup_old_backups(backups_dir: str,
                        dry_run: bool = False,
                        keep_all: int = 7,
                        keep_daily: int = 30,
                        keep_weekly: int = 52,
                        keep_monthly: int = 12,
                        keep_yearly: int = 5):
    """
    Delete old backups. Never deletes the only backup.
    For keep_* params threshold is inclusive, e.g.:
    keep_weekly=1 being run on Thursday will keep one backup from this week and
    one from the previous, even if the previous week's backup was created on
    Monday.
    keep_monthly=3 being run on any day of April will keep one backup from each
    of months of January, February and March.

    :param backups_dir: full path to backups directory.
    :param dry_run: don't do anything.
    :param keep_all:
        up to this amount of days in the past all backups must be kept.
    :param keep_daily:
        up to this amount of days in the past one daily backup must be kept.
    :param keep_weekly:
        up to this amount of weeks in the past one weekly backup must be kept.
    :param keep_monthly:
        up to this amount of months in the past one monthly backup must be kept.
        1 month is considered to be 30 days.
    :param keep_yearly:
        up to this amount of years in the past one yearly backup must be kept.
        1 year is considered to be 365 days.
    """
    all_backups = sorted(_iterate_backups(backups_dir),
                         key=lambda e: e.name, reverse=True)
    if dry_run:
        _lg.info("Dry-run, no backups will be actually removed")
    if not all_backups:
        _lg.debug("No backups, exiting")
        return
    if len(all_backups) == 1:
        _lg.debug("Only one backup (%s) exists, will not remove it",
                  all_backups[0].name)
        return

    now = datetime.now()
    thresholds = {k: now.strftime(BACKUP_ENT_FMT)
                  for k in ("all", "daily", "weekly", "monthly", "yearly")}
    if keep_all is not None:
        thresholds["all"] = ((now - timedelta(days=keep_all))
                             .replace(hour=0, minute=0, second=0)
                             .strftime(BACKUP_ENT_FMT))
    if keep_daily is not None:
        thresholds["daily"] = ((now - timedelta(days=keep_daily))
                               .replace(hour=0, minute=0, second=0)
                               .strftime(BACKUP_ENT_FMT))
    if keep_weekly is not None:
        thresholds["weekly"] = (
            (now - timedelta(weeks=keep_weekly, days=now.weekday()))
            .strftime(BACKUP_ENT_FMT)
        )
    if keep_monthly is not None:
        thresholds["monthly"] = ((now - timedelta(days=30*keep_monthly))
                                 .replace(day=1, hour=0, minute=0, second=0)
                                 .strftime(BACKUP_ENT_FMT))
    if keep_yearly is not None:
        thresholds["yearly"] = (
            (now - timedelta(days=365*keep_yearly))
            .replace(month=1, day=1, hour=0, minute=0, second=0)
            .strftime(BACKUP_ENT_FMT)
        )

    keep = _compute_retention_plan(all_backups, thresholds)
    # Validate the plan before deleting anything: the most recent snapshot
    # must always survive, and the plan can never invent a backup that
    # doesn't exist.
    assert all_backups[0] in keep, "retention plan drops the latest snapshot"
    assert keep <= set(all_backups), "retention plan keeps a phantom backup"

    backups_dir_abs = _canonical(backups_dir)
    repo_id = _ensure_repo_id(backups_dir)

    for backup in all_backups:
        if backup in keep:
            continue
        if dry_run:
            _lg.info("Would remove old backup %s", backup.name)
            continue
        _quarantine_and_delete(backup, backups_dir_abs, repo_id)


def _compute_retention_plan(all_backups: List[os.DirEntry],
                            thresholds: Dict[str, str]) -> set:
    """
    Compute the set of backups to retain. Each tier's retained set is
    computed independently from its own name range and unioned with the
    rest, so a coarser tier (e.g. monthly) can never override a decision
    a finer tier (e.g. weekly) already made about a backup that isn't
    even in the coarser tier's range - unlike carrying a single "previous
    backup compared against" value across tier boundaries, which is what
    let a coarser tier silently evict a backup a finer tier had decided
    to keep.
    """
    def _oldest_per_group(members, key_func) -> set:
        groups: Dict[object, os.DirEntry] = {}
        for member in members:
            key = key_func(member)
            if key not in groups or member.name < groups[key].name:
                groups[key] = member
        return set(groups.values())

    def _band(lower: str, upper: str) -> List[os.DirEntry]:
        return [b for b in all_backups if lower < b.name <= upper]

    keep = {all_backups[0]}  # the most recent snapshot is always retained

    keep |= {b for b in all_backups if b.name > thresholds["all"]}

    keep |= _oldest_per_group(
        _band(thresholds["daily"], thresholds["all"]),
        lambda b: _date_from_backup(b).date(),
    )

    keep |= _oldest_per_group(
        _band(thresholds["weekly"], thresholds["daily"]),
        # (ISO year, ISO week): ISO week alone collides across years, and
        # a year spanning ISO week 53 puts late-December dates in the
        # next ISO year - isocalendar() already accounts for both.
        lambda b: _date_from_backup(b).isocalendar()[:2],
    )

    keep |= _oldest_per_group(
        _band(thresholds["monthly"], thresholds["weekly"]),
        lambda b: (_date_from_backup(b).year, _date_from_backup(b).month),
    )

    keep |= _oldest_per_group(
        _band(thresholds["yearly"], thresholds["monthly"]),
        lambda b: _date_from_backup(b).year,
    )

    return keep


def _quarantine_and_delete(entry: os.DirEntry, backups_dir_abs: str,
                           repo_id: str):
    """
    Quarantine a retention deletion candidate before recursively removing
    it: rename it out of its snapshot name first. If the process crashes
    between the rename and the removal, the quarantined directory keeps
    the staging-dir prefix, so the existing stale-staging-dir cleanup -
    with the same boundary/mount/symlink safety checks - finishes
    removing it on the next run, rather than leaving a half-deleted
    directory sitting under its original snapshot name.
    """
    if not _verify_safe_to_delete(entry, backups_dir_abs, repo_id):
        return
    quarantine_path = os.path.join(
        backups_dir_abs, "%strash-%s" % (STAGING_PREFIX, entry.name)
    )
    try:
        os.rename(entry.path, quarantine_path)
    except OSError as err:
        _lg.error("Failed to quarantine %s before deletion: %s",
                  entry.path, err)
        return
    _lg.info("Removing old backup %s", entry.name)
    shutil.rmtree(quarantine_path, ignore_errors=True)


def process_backed_entry(backup_dir: str,
                         entry_relpath: str,
                         action: fs.Actions,
                         msg: str):
    """
    Additional processing of backed up DirEntry (file/dir/symlink).
    Actions:
    - if DirEntry was not deleted, hardlink it to DELTA_DIR.
    """
    _lg.debug("%s %s %s", action, entry_relpath, msg)
    if action not in (fs.Actions.ERROR, fs.Actions.DELETE):
        fs.nest_hardlink(src_dir=backup_dir, src_relpath=entry_relpath,
                         dst_dir=os.path.join(backup_dir, DELTA_DIR))


def initiate_backup(sources,
                    backups_dir: str,
                    dry_run: bool = False,
                    external_rsync: bool = False,
                    external_hardlink: bool = False
                    ) -> Optional[fs.PseudoDirEntry]:
    """
    Main backup function.
    Builds the new snapshot in a private ".incomplete-<name>" staging
    directory, copying data from the latest backup and then syncing data
    from sources. Any failure is fatal: the staging directory is discarded
    and BackupFailedError is raised, so a failed or interrupted backup can
    never be mistaken for a successful one. On success, the staging
    directory is fsync'd and atomically renamed into its final snapshot
    name.
    :param sources: list of directories to backup (relative paths ok)
    :param backups_dir: directory where all backups are stored
    :param dry_run: if True, no actual changes will be made
    :param external_rsync: if True, use external rsync instead of python
    :param external_hardlink: if True, use external hardlink instead of python
    :return: DirEntry-like object of the created snapshot, or None if no
        snapshot was created (dry-run or no changes since last backup).
    :raises BackupFailedError: if the backup could not be completed.
    """
    cleanup_stale_staging_dirs(backups_dir)

    snapshot_name = _reserve_snapshot_name(backups_dir)
    staging = fs.PseudoDirEntry(
        os.path.join(backups_dir, f"{STAGING_PREFIX}{snapshot_name}")
    )
    _lg.debug("Staging directory: %s", staging.path)

    latest_backup = _get_latest_backup(backups_dir)

    if latest_backup is None:
        _lg.info("Creating empty staging directory for backup: %s",
                 snapshot_name)
        try:
            os.mkdir(staging.path)
        except OSError as err:
            raise BackupFailedError(
                "Failed to create staging directory %s: %s"
                % (staging.path, err)
            ) from err

    else:
        _lg.info("Copying data from latest backup %s to staging for %s",
                 latest_backup.name, snapshot_name)

        hl_res = fs.hardlink_dir(src_dir=latest_backup.path,
                                 dst_dir=staging.path,
                                 use_external=external_hardlink)
        if not hl_res:
            _lg.error("Something went wrong during copying data from latest"
                      " backup, removing staging directory for %s",
                      snapshot_name)
            shutil.rmtree(staging.path, ignore_errors=True)
            raise BackupFailedError(
                "Failed to copy data from latest backup %s"
                % latest_backup.name
            )

        # remove backup markers from copied backup
        for fname in os.listdir(staging.path):
            if fname.startswith(BACKUP_MARKER):
                os.remove(os.path.join(staging.path, fname))

        # clean up delta dir from copied backup
        shutil.rmtree(os.path.join(staging.path, DELTA_DIR),
                      ignore_errors=True)

    rsync_func = fs.rsync_ext if external_rsync else fs.rsync

    backup_changed = False
    try:
        for src in sources:
            src_abs = os.path.abspath(src)
            src_name = os.path.basename(src_abs)
            dst_abs = os.path.join(staging.path, src_name)
            _lg.info("Backing up directory %s to staging for %s",
                     src_abs, snapshot_name)
            for entry_relpath, action, msg in rsync_func(
                    src_abs, dst_abs, dry_run=dry_run
            ):
                if action == fs.Actions.ERROR:
                    raise BackupFailedError(
                        "Failed to copy %s: %s" % (entry_relpath, msg)
                    )
                # TODO maybe should be run if first backup too?
                if latest_backup is not None:
                    process_backed_entry(
                        backup_dir=staging.path,
                        entry_relpath=os.path.join(src_name, entry_relpath),
                        action=action,
                        msg=msg,
                    )
                # raise flag if something was changed since last backup
                backup_changed = True
    except fs.BackupCreationError as err:
        _lg.error("Error during backup creation: %s", err)
        _lg.error("Failed to create backup %s, removing staging directory",
                  snapshot_name)
        shutil.rmtree(staging.path, ignore_errors=True)
        raise BackupFailedError(str(err)) from err
    except BackupFailedError:
        _lg.error("Failed to create backup %s, removing staging directory",
                  snapshot_name)
        shutil.rmtree(staging.path, ignore_errors=True)
        raise

    # do not create backup on dry-run
    if dry_run:
        _lg.info("Dry-run, removing staging directory: %s", snapshot_name)
        shutil.rmtree(staging.path, ignore_errors=True)
        return None
    # do not create backup if no change from previous one
    if latest_backup is not None and not backup_changed:
        _lg.info("Staged backup is the same as previous one %s, removing",
                 latest_backup.name)
        shutil.rmtree(staging.path, ignore_errors=True)
        return None

    # write and fsync completion manifest only after every source succeeded,
    # then atomically rename the staging dir into its final snapshot name
    marker_name = "%s_%s" % (BACKUP_MARKER, snapshot_name)
    _write_manifest(os.path.join(staging.path, marker_name),
                    backups_dir, snapshot_name)
    _fsync_dir(staging.path)

    final_path = os.path.join(backups_dir, snapshot_name)
    os.rename(staging.path, final_path)
    _fsync_dir(backups_dir)
    _lg.info("Backup created: %s", snapshot_name)
    return fs.PseudoDirEntry(final_path)
