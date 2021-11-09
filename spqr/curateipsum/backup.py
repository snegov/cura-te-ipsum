"""
Module with backup functions.
"""

import logging
import os
import shutil
import time
from datetime import datetime
from typing import Optional

import spqr.curateipsum.fs as fs

BACKUP_ENT_FMT = "%y%m%d_%H%M"
DELTA_DIR = "_delta"
_lg = logging.getLogger(__name__)


def _is_backup_entity(entity_path: str) -> bool:
    """ Check if entity_path is a single backup dir. """
    if not os.path.isdir(entity_path):
        return False
    try:
        datetime.strptime(os.path.basename(entity_path), BACKUP_ENT_FMT)
        return True
    except ValueError:
        return False


def _get_latest_backup(backup_dir: str) -> Optional[str]:
    """ Returns path to latest backup created in backup_dir or None. """
    backups = sorted(os.listdir(backup_dir), reverse=True)

    for b_ent in backups:
        b_ent_abs = os.path.join(backup_dir, b_ent)
        if not _is_backup_entity(b_ent_abs):
            continue
        if not os.listdir(b_ent_abs):
            _lg.info("Removing empty backup entity: %s", os.path.basename(b_ent_abs))
            os.rmdir(b_ent_abs)
            continue
        return b_ent_abs

    return None


def process_backed_entry(backup_dir: str, entry_relpath: str, action: fs.Actions):
    _lg.debug("%s %s", action, entry_relpath)
    if action is not fs.Actions.delete:
        fs.nest_hardlink(src_dir=backup_dir, src_relpath=entry_relpath,
                         dst_dir=os.path.join(backup_dir, DELTA_DIR))


def initiate_backup(sources,
                    backup_dir: str,
                    dry_run: bool = False,
                    external_rsync: bool = False,
                    external_hardlink: bool = False):
    """ Main backup function """

    start_time = time.time()
    start_time_fmt = datetime.fromtimestamp(start_time).strftime(BACKUP_ENT_FMT)
    cur_backup = os.path.join(backup_dir, start_time_fmt)
    cur_backup_name = os.path.basename(cur_backup)
    _lg.debug("Current backup dir: %s", cur_backup)

    latest_backup = _get_latest_backup(backup_dir)
    if cur_backup == latest_backup:
        _lg.warning("Latest backup %s was created less than minute ago, exiting",
                    os.path.basename(latest_backup))
        return

    if latest_backup is None:
        _lg.info("Creating empty directory for current backup: %s", cur_backup_name)
        os.mkdir(cur_backup)
    else:
        _lg.info("Copying data from latest backup %s to current backup %s",
                 os.path.basename(latest_backup), cur_backup_name)

        hl_res = fs.hardlink_dir(src_dir=latest_backup, dst_dir=cur_backup,
                                 use_external=external_hardlink)
        if not hl_res:
            _lg.error("Something went wrong during copying data from latest backup,"
                      " removing created %s", cur_backup_name)
            shutil.rmtree(cur_backup, ignore_errors=True)
            return

        # clean up delta dir from copied backup
        shutil.rmtree(os.path.join(cur_backup, DELTA_DIR), ignore_errors=True)

    rsync_func = fs.rsync_ext if external_rsync else fs.rsync

    backup_changed = False
    for src in sources:
        src_abs = os.path.abspath(src)
        src_name = os.path.basename(src_abs)
        dst_abs = os.path.join(cur_backup, src_name)
        _lg.info("Backing up directory %s to %s backup", src_abs, cur_backup_name)
        for entry_relpath, action in rsync_func(src_abs, dst_abs, dry_run=dry_run):
            if latest_backup is not None:
                process_backed_entry(
                    backup_dir=cur_backup,
                    entry_relpath=os.path.join(src_name, entry_relpath),
                    action=action
                )
            backup_changed = True

    # do not create backup on dry-run
    if dry_run:
        _lg.info("Dry-run, removing created backup: %s", cur_backup_name)
        shutil.rmtree(cur_backup, ignore_errors=True)
    # do not create backup if no change from previous one
    elif latest_backup is not None and not backup_changed:
        _lg.info("Newly created backup %s is the same as previous one %s, removing",
                 cur_backup_name, os.path.basename(latest_backup))
        shutil.rmtree(cur_backup, ignore_errors=True)
    else:
        _lg.info("Backup created: %s", cur_backup_name)

    end_time = time.time()
    spend_time = end_time - start_time
    _lg.info("Finished, time spent: %.3fs", spend_time)
