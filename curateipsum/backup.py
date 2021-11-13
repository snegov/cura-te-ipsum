"""
Module with backup functions.
"""

import logging
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, Iterable

from curateipsum import fs

BACKUP_ENT_FMT = "%Y%m%d_%H%M%S"
LOCK_FILE = ".backups_lock"
DELTA_DIR = ".backup_delta"
_lg = logging.getLogger(__name__)


def _is_backup_entity(backup_entry: os.DirEntry) -> bool:
    """ Check if entity_path is a single backup dir. """
    if not backup_entry.is_dir():
        return False
    try:
        datetime.strptime(backup_entry.name, BACKUP_ENT_FMT)
        return True
    except ValueError:
        return False


def _iterate_backups(backup_dir: str) -> Iterable[os.DirEntry]:
    b_iter = os.scandir(backup_dir)

    b_ent: os.DirEntry
    for b_ent in b_iter:
        if not _is_backup_entity(b_ent):
            continue
        if not os.listdir(b_ent.path):
            _lg.info("Removing empty backup entity: %s", b_ent.name)
            os.rmdir(b_ent.path)
            continue
        yield b_ent

    b_iter.close()


def _get_latest_backup(backup_dir: str) -> Optional[os.DirEntry]:
    """ Returns path to latest backup created in backup_dir or None. """
    all_backups = sorted(_iterate_backups(backup_dir), key=lambda e: e.name)
    if all_backups:
        return all_backups[-1]
    return None


def _date_from_backup(backup: os.DirEntry) -> datetime:
    return datetime.strptime(backup.name, BACKUP_ENT_FMT)


def set_backups_lock(backup_dir: str, force: bool = False) -> bool:
    """ Return false if previous backup is still running. """
    lock_file_path = os.path.join(backup_dir, LOCK_FILE)
    if os.path.exists(lock_file_path):
        if not force:
            return False
        os.unlink(lock_file_path)

    open(lock_file_path, "a").close()
    return True


def release_backups_lock(backup_dir: str):
    lock_file_path = os.path.join(backup_dir, LOCK_FILE)
    if os.path.exists(lock_file_path):
        os.unlink(lock_file_path)


def cleanup_old_backups(
        backup_dir: str,
        dry_run: bool = False,
        keep_all: int = 7,
        keep_daily: int = 30,
        keep_weekly: int = 52,
        keep_monthly: int = 12,
        keep_yearly: int = 5,
        min_free_space: int = 0
):
    """
    Delete old backups. Never deletes the only backup.
    :param backup_dir: full path to backup directory.
    :param dry_run: don't do anything actually.
    :param keep_all: the number of days that all backups must be kept.
    :param keep_daily: the number of days that all daily backups must be kept.
    :param keep_weekly: the number of weeks of which one weekly backup must be kept.
    :param keep_monthly: the number of months (1 month = 30 days) of which
        one monthly backup must be kept.
    :param keep_yearly: the number of years of which one yearly backup must be kept.
    :param min_free_space: not used right now
    :return:
    """
    all_backups = sorted(_iterate_backups(backup_dir),
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
        if not dry_run and do_delete:
            _lg.info("Removing old backup %s", backup.name)
            shutil.rmtree(backup.path)


def process_backed_entry(backup_dir: str, entry_relpath: str, action: fs.Actions):
    _lg.debug("%s %s", action, entry_relpath)
    if action is not fs.Actions.DELETE:
        fs.nest_hardlink(src_dir=backup_dir, src_relpath=entry_relpath,
                         dst_dir=os.path.join(backup_dir, DELTA_DIR))


def initiate_backup(sources,
                    backup_dir: str,
                    dry_run: bool = False,
                    external_rsync: bool = False,
                    external_hardlink: bool = False):
    """ Main backup function """

    start_time_fmt = datetime.now().strftime(BACKUP_ENT_FMT)
    cur_backup = fs.PseudoDirEntry(os.path.join(backup_dir, start_time_fmt))
    _lg.debug("Current backup dir: %s", cur_backup.path)

    latest_backup = _get_latest_backup(backup_dir)

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
            _lg.error("Something went wrong during copying data from latest backup,"
                      " removing created %s", cur_backup.name)
            shutil.rmtree(cur_backup.path, ignore_errors=True)
            return

        # clean up delta dir from copied backup
        shutil.rmtree(os.path.join(cur_backup.path, DELTA_DIR), ignore_errors=True)

    rsync_func = fs.rsync_ext if external_rsync else fs.rsync

    backup_changed = False
    for src in sources:
        src_abs = os.path.abspath(src)
        src_name = os.path.basename(src_abs)
        dst_abs = os.path.join(cur_backup.path, src_name)
        _lg.info("Backing up directory %s to %s backup", src_abs, cur_backup.name)
        for entry_relpath, action in rsync_func(src_abs, dst_abs, dry_run=dry_run):
            if latest_backup is not None:
                process_backed_entry(
                    backup_dir=cur_backup.path,
                    entry_relpath=os.path.join(src_name, entry_relpath),
                    action=action
                )
            backup_changed = True

    # do not create backup on dry-run
    if dry_run:
        _lg.info("Dry-run, removing created backup: %s", cur_backup.name)
        shutil.rmtree(cur_backup.path, ignore_errors=True)
    # do not create backup if no change from previous one
    elif latest_backup is not None and not backup_changed:
        _lg.info("Newly created backup %s is the same as previous one %s, removing",
                 cur_backup.name, latest_backup.name)
        shutil.rmtree(cur_backup.path, ignore_errors=True)
    else:
        _lg.info("Backup created: %s", cur_backup.name)
