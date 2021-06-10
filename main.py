#!/usr/bin/env python

import argparse
import logging
import os.path
import pathlib
import sys

from spqr.curateipsum.backup import initiate_backup

_lg = logging.getLogger("spqr.curateipsum")


def main():
    formatter = logging.Formatter("{asctime}|{levelname}|{message}", style="{")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    parser = argparse.ArgumentParser(
        prog="cura-te-ipsum", description="cura-te-ipsum, my personal backup software.",
    )
    parser.add_argument("-V", "--version", action="version", version="%(prog)s 0.1")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="print verbose information",
    )
    parser.add_argument(
        "-b",
        type=pathlib.Path,
        dest="backup_dir",
        metavar="BACKUP_DIR",
        required=True,
        help="directory, where all backups will be stored",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        metavar="SOURCE",
        type=pathlib.Path,
        help="backup source (file/dir/smth else)",
    )
    args = parser.parse_args()

    loglevel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=loglevel, handlers=[console_handler])

    _lg.info("Starting %s: %s", parser.prog, args)
    backup_dir_abs = pathlib.Path(os.path.abspath(args.backup_dir))
    if not os.path.isdir(backup_dir_abs):
        _lg.error("Backup directory %s does not exist, exiting", args.backup_dir)
        return 1

    for src_dir in args.sources:
        if not os.path.isdir(src_dir):
            _lg.error("Source directory %s does not exist", src_dir)
            return 1

    initiate_backup(args.sources, backup_dir_abs)


if __name__ == "__main__":
    sys.exit(main())
