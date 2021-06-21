"""
Module with backup functions.
"""

import logging
import os
import pathlib
import shutil
from datetime import datetime
from typing import Optional

from spqr.curateipsum.fs import hardlink_dir, rsync

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

    cur_backup = pathlib.Path(
        os.path.join(backup_dir, datetime.now().strftime(BACKUP_ENT_FMT))
    )
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

        hardlink_dir(latest_backup, cur_backup)

    # for src in sources:
    #     src_abs = pathlib.Path(os.path.abspath(src))
    #     dst_abs = pathlib.Path(os.path.join(cur_backup, src_abs.name))
    #     _lg.info("Backing up directory %s to %s backup", src_abs, cur_backup.name)
    #     rsync(src_abs, cur_backup)
    if dry_run:
        _lg.info("Dry-run, removing created backup: %s", cur_backup.name)
        shutil.rmtree(cur_backup, ignore_errors=True)
    else:
        _lg.info("Backup created: %s", cur_backup.name)
