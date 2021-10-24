#!/usr/bin/env python

import argparse
import logging
import os.path
import pathlib
import shutil
import sys

from spqr.curateipsum.backup import initiate_backup

_lg = logging.getLogger("spqr.curateipsum")
SUPPORTED_PLATFORMS = ("linux", "darwin")


def main():
    formatter = logging.Formatter("{asctime}|{levelname}|{message}", style="{")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    parser = argparse.ArgumentParser(
        prog="cura-te-ipsum", description="cura-te-ipsum, my personal backup software.",
    )
    parser.add_argument("-V", "--version", action="version", version="%(prog)s 0.1")
    parser.add_argument("-v", "--verbose",
                        action="store_true",
                        default=False,
                        help="print verbose information")
    parser.add_argument("-b",
                        dest="backup_dir",
                        metavar="BACKUP_DIR",
                        type=pathlib.Path,
                        required=True,
                        help="directory, where all backups will be stored")
    parser.add_argument("-n", "--dry-run",
                        action="store_true",
                        default=False,
                        help="Do not do create backup")
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
                        type=pathlib.Path,
                        help="backup source (file/dir/smth else)")
    args = parser.parse_args()

    loglevel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=loglevel, handlers=[console_handler])

    _lg.info("Starting %s: %s", parser.prog, args)

    if sys.platform not in SUPPORTED_PLATFORMS:
        _lg.error(f"Not supported platform: {sys.platform}. Supported platforms: {SUPPORTED_PLATFORMS}")
        return 1

    if args.external_rsync and not shutil.which("rsync"):
        _lg.error("rsync should be installed to use --external-rsync option.")
        return 1

    cp_program = "gcp" if sys.platform == "darwin" else "cp"
    if args.external_hardlink and not shutil.which(cp_program):
        _lg.error(f"{cp_program} should be installed to use --external-hardlink option.")
        return 1

    backup_dir_abs = pathlib.Path(os.path.abspath(args.backup_dir))
    if not os.path.isdir(backup_dir_abs):
        _lg.error("Backup directory %s does not exist, exiting", args.backup_dir)
        return 1

    for src_dir in args.sources:
        if not os.path.isdir(src_dir):
            _lg.error("Source directory %s does not exist", src_dir)
            return 1

    initiate_backup(
        sources=args.sources,
        backup_dir=backup_dir_abs,
        dry_run=args.dry_run,
        external_rsync=args.external_rsync,
        external_hardlink=args.external_hardlink,
    )


if __name__ == "__main__":
    sys.exit(main())
