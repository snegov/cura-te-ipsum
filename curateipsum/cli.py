#!/usr/bin/env python

import argparse
import logging
import os.path
import shutil
import sys
import time
from datetime import timedelta

from curateipsum import backup
from curateipsum._version import version

_lg = logging.getLogger("curateipsum")
SUPPORTED_PLATFORMS = ("linux", "darwin")


def main():
    formatter = logging.Formatter("{asctime}|{levelname}|{message}", style="{")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    parser = argparse.ArgumentParser(
        prog="cura-te-ipsum",
        description="cura-te-ipsum, my personal backup software.",
    )
    parser.add_argument("-V", "--version",
                        action="version",
                        version=f"%(prog)s v{version}")
    parser.add_argument("-v", "--verbose",
                        action="store_true",
                        default=False,
                        help="print verbose information")
    parser.add_argument("-b",
                        dest="backups_dir",
                        metavar="BACKUPS_DIR",
                        type=str,
                        required=True,
                        help="directory, where all backups will be stored")
    parser.add_argument("-n", "--dry-run",
                        action="store_true",
                        default=False,
                        help="Do not do create backup")
    parser.add_argument("-f", "--force",
                        action="store_true",
                        default=False,
                        help="Force run when previous backup is still in process")
    parser.add_argument("--external-rsync",
                        action="store_true",
                        default=False,
                        help="Use external rsync for copying")
    parser.add_argument("--external-hardlink",
                        action="store_true",
                        default=False,
                        help="Use cp command for creating hardlink copies")
    parser.add_argument("sources",
                        nargs="+",
                        metavar="SOURCE",
                        type=str,
                        help="backup source (file/dir/smth else)")
    args = parser.parse_args()

    loglevel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=loglevel, handlers=[console_handler])

    _lg.info("Starting %s: %s", parser.prog, args)

    if sys.platform not in SUPPORTED_PLATFORMS:
        _lg.error("Not supported platform: %s. Supported platforms: %s",
                  sys.platform, SUPPORTED_PLATFORMS)
        return 1

    if args.external_rsync and not shutil.which("rsync"):
        _lg.error("rsync should be installed to use --external-rsync option.")
        return 1

    cp_program = "gcp" if sys.platform == "darwin" else "cp"
    if args.external_hardlink and not shutil.which(cp_program):
        _lg.error("%s should be installed to use --external-hardlink option.",
                  cp_program)
        return 1

    backups_dir_abs = os.path.abspath(args.backups_dir)
    if not os.path.isdir(backups_dir_abs):
        _lg.error("Backup directory %s does not exist, exiting",
                  args.backups_dir)
        return 1

    for src_dir in args.sources:
        if not os.path.isdir(src_dir):
            _lg.error("Source directory %s does not exist", src_dir)
            return 1

    start_time = time.time()

    if not backup.set_backups_lock(backups_dir_abs, args.force):
        return 1

    # TODO add cleaning up from non-finished backups
    backup.cleanup_old_backups(backups_dir=backups_dir_abs,
                               dry_run=args.dry_run)
    backup.initiate_backup(
        sources=args.sources,
        backups_dir=backups_dir_abs,
        dry_run=args.dry_run,
        external_rsync=args.external_rsync,
        external_hardlink=args.external_hardlink,
    )
    backup.release_backups_lock(backups_dir_abs)

    end_time = time.time()
    _lg.info("Finished, time spent: %s", str(timedelta(end_time - start_time)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
