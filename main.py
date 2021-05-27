#!/usr/bin/env python

import argparse
import logging
import os.path
import pathlib
import sys

_lg = logging.getLogger('spqr.curateipsum')


def main():
    formatter = logging.Formatter("{asctime}|{levelname}|{message}", style="{")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    parser = argparse.ArgumentParser(
        prog="cura-te-ipsum",
        description="cura-te-ipsum, my personal backup software.",
    )
    parser.add_argument("-V", "--version", action="version", version="%(prog)s 0.1")
    parser.add_argument("-v", "--verbose", action="store_true", default=False,
                        help="print verbose information")
    parser.add_argument("-b", type=pathlib.Path, dest="backup_dir",
                        metavar="BACKUP_DIR", required=True,
                        help="directory, where all backups will be stored")
    parser.add_argument("src_dirs", nargs="+", metavar="SRC_DIR", type=pathlib.Path,
                        help="directory, which should be backed up")
    args = parser.parse_args()

    loglevel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=loglevel, handlers=[console_handler])

    backup_dir_abs = os.path.abspath(args.backup_dir)
    if not os.path.isdir(backup_dir_abs):
        _lg.error("Backup directory %s does not exist, exiting", args.backup_dir)
        return 1

    # fs.hardlink_dir(sys.argv[1], sys.argv[2])
    # fs.rsync(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
