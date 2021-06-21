"""
Module with backup functions.
"""

import logging
import os
import pathlib
import shutil
import time
from datetime import datetime
from typing import Optional

import spqr.curateipsum.fs as fs

BACKUP_ENT_FMT = "%y%m%d_%H%M"
_lg = logging.getLogger(__name__)


def _is_backup_entity(entity_path: pathlib.Path) -> bool:
    """ Check if entity_path is a single backup dir. """
    try:
        datetime.strptime(entity_path.name, BACKUP_ENT_FMT)
        return True
    except ValueError:
        return False


def _get_latest_backup(backup_dir: pathlib.Path) -> Optional[pathlib.Path]:
    """ Returns path to latest backup created in backup_dir or None. """
    backups = sorted(os.listdir(backup_dir), reverse=True)

    for b_ent in backups:
        b_ent_abs = pathlib.Path(os.path.join(backup_dir, b_ent))

        if not _is_backup_entity(b_ent_abs):
            continue

        if not os.listdir(b_ent_abs):
            _lg.info("Removing empty backup entity: %s", b_ent_abs.name)
            _lg.debug("Removing directory %s", b_ent_abs)
            os.rmdir(b_ent_abs)
            continue

        return b_ent_abs

    return None


def initiate_backup(sources, backup_dir: pathlib.Path, dry_run=False):
    """ Main backup function """

    start_time = time.time()
    start_time_fmt = datetime.fromtimestamp(start_time).strftime(BACKUP_ENT_FMT)
    cur_backup = backup_dir / start_time_fmt
    _lg.debug("Current backup dir: %s", cur_backup)

    latest_backup = _get_latest_backup(backup_dir)
    if cur_backup == latest_backup:
        _lg.warning(
            "Latest backup %s was created less than minute ago, exiting",
            latest_backup.name,
        )
        return

    if latest_backup is None:
        _lg.info("Creating empty directory for current backup: %s", cur_backup.name)
        os.mkdir(cur_backup)
    else:
        _lg.info(
            "Copying data from latest backup %s to current backup %s",
            latest_backup.name,
            cur_backup.name,
        )

        hl_res = fs.hardlink_dir(latest_backup, cur_backup)
        if not hl_res:
            _lg.error("Something went wrong during copying data from latest backup,"
                      " removing created %s", cur_backup.name)
            shutil.rmtree(cur_backup, ignore_errors=True)
            return
    if dry_run:
        _lg.info("Dry-run, removing created backup: %s", cur_backup.name)
        shutil.rmtree(cur_backup, ignore_errors=True)
    else:
        _lg.info("Backup created: %s", cur_backup.name)

    end_time = time.time()
    spend_time = end_time - start_time
    _lg.info("Finished, time spent: %.3fs", spend_time)
