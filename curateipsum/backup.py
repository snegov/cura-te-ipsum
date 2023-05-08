"""
Module with backup functions.
"""
import errno
import logging
import os
import shutil
import signal
from datetime import datetime, timedelta
from typing import Optional, Iterable, Union

from curateipsum import fs

BACKUP_ENT_FMT = "%Y%m%d_%H%M%S"
LOCK_FILE = ".backups_lock"
DELTA_DIR = ".backup_delta"
BACKUP_MARKER = ".backup_finished"
_lg = logging.getLogger(__name__)


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

    if not os.path.exists(lock_file_path):
        with open(lock_file_path, "a") as f:
            f.write(str(os.getpid()))
        return True

    with open(lock_file_path, "r") as f:
        pid = int(f.read())

    if _pid_exists(pid):
        if not force:
            _lg.warning(
                "Previous backup is still in progress (PID: %d), exiting", pid
            )
            return False

        _lg.warning(
            "Previous backup is still in progress (PID: %d), "
            "but force flag is set, continuing", pid
        )
        os.kill(pid, signal.SIGKILL)

    os.unlink(lock_file_path)
    return True


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
                    external_hardlink: bool = False):
    """
    Main backup function.
    Creates a new backup directory, copies data from the latest backup,
    and then syncs data from sources.
    :param sources: list of directories to backup (relative paths ok)
    :param backups_dir: directory where all backups are stored
    :param dry_run: if True, no actual changes will be made
    :param external_rsync: if True, use external rsync instead of python
    :param external_hardlink: if True, use external hardlink instead of python
    """

    start_time_fmt = datetime.now().strftime(BACKUP_ENT_FMT)
    cur_backup = fs.PseudoDirEntry(os.path.join(backups_dir, start_time_fmt))
    _lg.debug("Current backup dir: %s", cur_backup.path)

    latest_backup = _get_latest_backup(backups_dir)

    if latest_backup is None:
        _lg.info("Creating empty directory for current backup: %s",
                 cur_backup.name)
        os.mkdir(cur_backup.path)

    else:
        _lg.info("Copying data from latest backup %s to current backup %s",
                 latest_backup.name, cur_backup.name)

        hl_res = fs.hardlink_dir(src_dir=latest_backup.path,
                                 dst_dir=cur_backup.path,
                                 use_external=external_hardlink)
        if not hl_res:
            _lg.error("Something went wrong during copying data from latest"
                      " backup, removing created %s", cur_backup.name)
            shutil.rmtree(cur_backup.path, ignore_errors=True)
            return

        # remove backup markers from copied backup
        for fname in os.listdir(cur_backup.path):
            if fname.startswith(BACKUP_MARKER):
                os.remove(os.path.join(cur_backup.path, fname))

        # clean up delta dir from copied backup
        shutil.rmtree(os.path.join(cur_backup.path, DELTA_DIR),
                      ignore_errors=True)

    rsync_func = fs.rsync_ext if external_rsync else fs.rsync

    backup_changed = False
    for src in sources:
        src_abs = os.path.abspath(src)
        src_name = os.path.basename(src_abs)
        dst_abs = os.path.join(cur_backup.path, src_name)
        _lg.info("Backing up directory %s to backup %s",
                 src_abs, cur_backup.name)
        try:
            for entry_relpath, action, msg in rsync_func(
                    src_abs, dst_abs, dry_run=dry_run
            ):
                # TODO maybe should be run if first backup too?
                if latest_backup is not None:
                    process_backed_entry(
                        backup_dir=cur_backup.path,
                        entry_relpath=os.path.join(src_name, entry_relpath),
                        action=action,
                        msg=msg,
                    )
                # raise flag if something was changed since last backup
                backup_changed = True
        except fs.BackupCreationError as err:
            _lg.error("Error during backup creation: %s", err)
            _lg.error("Failed to create backup %s, removing", cur_backup.name)
            shutil.rmtree(cur_backup.path, ignore_errors=True)

    # do not create backup on dry-run
    if dry_run:
        _lg.info("Dry-run, removing created backup: %s", cur_backup.name)
        shutil.rmtree(cur_backup.path, ignore_errors=True)
    # do not create backup if no change from previous one
    elif latest_backup is not None and not backup_changed:
        _lg.info("Created backup %s is the same as previous one %s, removing",
                 cur_backup.name, latest_backup.name)
        shutil.rmtree(cur_backup.path, ignore_errors=True)
    else:
        set_backup_marker(cur_backup)
        _lg.info("Backup created: %s", cur_backup.name)
