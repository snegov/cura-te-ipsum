"""
Module with backup functions.
"""
import errno
import logging
import os
import shutil
import signal
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, Iterable, Union

from curateipsum import fs

BACKUP_ENT_FMT = "%Y%m%d_%H%M%S"
LOCK_FILE = ".backups_lock"
DELTA_DIR = ".backup_delta"
BACKUP_MARKER = ".backup_finished"
STAGING_PREFIX = ".incomplete-"
_lg = logging.getLogger(__name__)


class BackupFailedError(Exception):
    """Raised when a backup could not be completed successfully.

    Any failure while building a snapshot (copy error, parse error,
    unsupported entry, nonzero subprocess exit) is fatal: the partially
    built snapshot is discarded and this is the only way that failure is
    reported to callers.
    """


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


def _pid_exists(pid: int) -> bool:
    """Check whether pid exists in the current process table."""
    if pid == 0:
        # According to "man 2 kill" PID 0 has a special meaning:
        # it refers to <<every process in the process group of the
        # calling process>> so we don't want to go any further.
        # If we get here it means this UNIX platform *does* have
        # a process with id 0.
        return True
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            # ESRCH == No such process
            return False
        elif err.errno == errno.EPERM:
            # EPERM clearly means there's a process to deny access to
            return True
        else:
            # According to "man 2 kill" possible error values are
            # (EINVAL, EPERM, ESRCH) therefore we should never get
            # here. If we do let's be explicit in considering this
            # an error.
            raise err
    else:
        return True


def set_backups_lock(backups_dir: str,
                     force: bool = False) -> bool:
    """
    Set lock file to prevent multiple backups running at the same time.
    Lock file contains PID of the process that created it.
    Return false if previous backup is still running and force flag is not set.
    """
    lock_file_path = os.path.join(backups_dir, LOCK_FILE)

    # Try to create lock file atomically
    try:
        fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Lock file already exists, check if process is still running
        pass

    # Read existing lock file
    try:
        with open(lock_file_path, "r") as f:
            content = f.read().strip()
            if not content:
                raise ValueError("Lock file is empty")
            pid = int(content)
    except (ValueError, IOError) as e:
        _lg.warning("Corrupted lock file (%s), removing and retrying", e)
        try:
            os.unlink(lock_file_path)
        except OSError:
            pass
        return set_backups_lock(backups_dir, force)

    if _pid_exists(pid):
        if not force:
            _lg.warning(
                "Previous backup is still in progress (PID: %d), exiting", pid
            )
            return False

        _lg.warning(
            "Previous backup is still in progress (PID: %d), "
            "but force flag is set, attempting graceful termination", pid
        )
        # Try SIGTERM first for graceful shutdown
        try:
            os.kill(pid, signal.SIGTERM)
            _lg.info("Sent SIGTERM to process %d, waiting 5 seconds", pid)
            time.sleep(5)

            # Check if process is still running
            if _pid_exists(pid):
                _lg.warning("Process %d did not terminate, sending SIGKILL", pid)
                os.kill(pid, signal.SIGKILL)
                time.sleep(1)  # Brief wait for SIGKILL to take effect
        except OSError as e:
            _lg.error("Failed to kill process %d: %s", pid, e)
            return False

    # Remove stale lock file and retry
    try:
        os.unlink(lock_file_path)
    except OSError as e:
        _lg.error("Failed to remove lock file: %s", e)
        return False

    return set_backups_lock(backups_dir, force)


def release_backups_lock(backups_dir: str):
    """Remove lock file."""
    lock_file_path = os.path.join(backups_dir, LOCK_FILE)
    if os.path.exists(lock_file_path):
        os.unlink(lock_file_path)


def set_backup_marker(backup_entry: Union[os.DirEntry, fs.PseudoDirEntry]):
    """Create finished backup marker file in backup's directory."""
    backup_marker = _get_backup_marker(backup_entry)
    if not os.path.exists(backup_marker.path):
        open(backup_marker.path, "a").close()


def _fsync_dir(path: str):
    """Fsync a directory so its content is durable before it is renamed."""
    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _reserve_snapshot_name(backups_dir: str) -> str:
    """
    Return a snapshot name that doesn't collide with an existing entry.
    Guards against two backups started within the same second.
    """
    name = datetime.now().strftime(BACKUP_ENT_FMT)
    while os.path.lexists(os.path.join(backups_dir, name)):
        time.sleep(1)
        name = datetime.now().strftime(BACKUP_ENT_FMT)
    return name


def cleanup_stale_staging_dirs(backups_dir: str):
    """
    Remove staging directories abandoned by a crashed or interrupted
    backup run. Must be called before a new backup starts so a stale
    staging directory can never be mistaken for a real snapshot.
    """
    with os.scandir(backups_dir) as it:
        entry: os.DirEntry
        for entry in it:
            if entry.name.startswith(STAGING_PREFIX) and entry.is_dir():
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

    prev_backup = all_backups[0]
    to_remove = {b: False for b in all_backups}

    for backup in all_backups[1:]:
        # skip all backups made after threshold
        if backup.name > thresholds["all"]:
            prev_backup = backup
            continue

        # leave only one backup per day for backups made after threshold
        if backup.name > thresholds["daily"]:
            if (_date_from_backup(prev_backup).date()
                    == _date_from_backup(backup).date()):
                to_remove[prev_backup] = True
            prev_backup = backup
            continue

        # leave only one backup per week for backups made after threshold
        if backup.name > thresholds["weekly"]:
            if (_date_from_backup(prev_backup).isocalendar()[1]
                    == _date_from_backup(backup).isocalendar()[1]):
                to_remove[prev_backup] = True
            prev_backup = backup
            continue

        # leave only one backup per month for backups made after threshold
        if backup.name > thresholds["monthly"]:
            if (_date_from_backup(prev_backup).date().replace(day=1)
                    == _date_from_backup(backup).date().replace(day=1)):
                to_remove[prev_backup] = True
            prev_backup = backup
            continue

        # leave only one backup per year for backups made after threshold
        if backup.name > thresholds["yearly"]:
            if (_date_from_backup(prev_backup).date().replace(month=1, day=1)
                    == _date_from_backup(backup).date().replace(month=1, day=1)):
                to_remove[prev_backup] = True
            prev_backup = backup
            continue

        to_remove[backup] = True

    for backup, do_delete in to_remove.items():
        if do_delete:
            if dry_run:
                _lg.info("Would remove old backup %s", backup.name)
            else:
                _lg.info("Removing old backup %s", backup.name)
                shutil.rmtree(backup.path)


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
        os.mkdir(staging.path)

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
    except (fs.BackupCreationError, BackupFailedError) as err:
        _lg.error("Error during backup creation: %s", err)
        _lg.error("Failed to create backup %s, removing staging directory",
                  snapshot_name)
        shutil.rmtree(staging.path, ignore_errors=True)
        raise BackupFailedError(str(err)) from err

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

    # write and fsync completion marker only after every source succeeded,
    # then atomically rename the staging dir into its final snapshot name
    marker_name = "%s_%s" % (BACKUP_MARKER, snapshot_name)
    open(os.path.join(staging.path, marker_name), "a").close()
    _fsync_dir(staging.path)

    final_path = os.path.join(backups_dir, snapshot_name)
    os.rename(staging.path, final_path)
    _lg.info("Backup created: %s", snapshot_name)
    return fs.PseudoDirEntry(final_path)
