#!/usr/bin/env python

import argparse
import logging
import os.path
import shutil
import sys
import time
from datetime import timedelta

from curateipsum import backup, restore
from curateipsum._version import version

_lg = logging.getLogger("curateipsum")
SUPPORTED_PLATFORMS = ("linux", "darwin")
_SUBCOMMANDS = ("backup", "restore")
_TOP_LEVEL_FLAGS = ("-h", "--help", "-V", "--version")


def _normalize_argv(argv):
    """
    Insert the implicit "backup" subcommand when argv doesn't already
    start with a known subcommand or a top-level flag (-h/-V), so
    existing invocations like `cura-te-ipsum -b DIR SRC` keep working
    unchanged now that `restore` exists alongside `backup`.
    """
    if argv and (argv[0] in _SUBCOMMANDS or argv[0] in _TOP_LEVEL_FLAGS):
        return argv
    return ["backup", *argv]


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="cura-te-ipsum",
        description="cura-te-ipsum, my personal backup software.",
    )
    parser.add_argument("-V", "--version",
                        action="version",
                        version=f"%(prog)s v{version}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose",
                        action="store_true",
                        default=False,
                        help="print verbose information")
    common.add_argument("-b",
                        dest="backups_dir",
                        metavar="BACKUPS_DIR",
                        type=str,
                        required=True,
                        help="directory, where all backups will be stored")
    common.add_argument("-f", "--force",
                        action="store_true",
                        default=False,
                        help="Wait for a running backup/restore to finish "
                             "instead of exiting immediately")
    common.add_argument("-n", "--dry-run",
                        action="store_true",
                        default=False,
                        help="show what would be done, without doing it")

    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser(
        "backup", parents=[common], help="create a new backup")
    backup_parser.add_argument("--external-rsync",
                               action="store_true",
                               default=False,
                               help="Use external rsync for copying")
    backup_parser.add_argument("--external-hardlink",
                               action="store_true",
                               default=False,
                               help="Use cp command for creating hardlink "
                                    "copies")
    backup_parser.add_argument("sources",
                               nargs="+",
                               metavar="SOURCE",
                               type=str,
                               help="backup source (file/dir/smth else)")

    restore_parser = subparsers.add_parser(
        "restore", parents=[common], help="restore a backed-up snapshot")
    restore_parser.add_argument("--snapshot",
                                dest="snapshot_name",
                                metavar="NAME",
                                default=None,
                                help="snapshot to restore, e.g. "
                                     "20260101_120000 (default: latest)")
    restore_parser.add_argument("--overwrite",
                                choices=restore.OVERWRITE_POLICIES,
                                default=restore.OVERWRITE_NEVER,
                                help="what to do when a destination path "
                                     "already exists (default: %(default)s)")
    restore_parser.add_argument("--verify",
                                action="store_true",
                                default=False,
                                help="verify restored content against the "
                                     "snapshot manifest afterwards")
    restore_parser.add_argument("dest",
                                metavar="DEST",
                                type=str,
                                help="directory to restore into")
    restore_parser.add_argument("paths",
                                nargs="*",
                                metavar="PATH",
                                help="restore only these snapshot-relative "
                                     "paths - each starts with the source "
                                     "directory's basename, e.g. "
                                     "'mydir/subdir/file.txt' for a source "
                                     "backed up from /home/user/mydir "
                                     "(default: restore everything)")

    return parser


def _run_backup(args) -> int:
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

    try:
        backup.validate_topology(args.sources, backups_dir_abs)
    except backup.BackupFailedError as err:
        _lg.error("Unsafe source/backups layout: %s", err)
        return 1

    start_time = time.time()

    if not backup.set_backups_lock(backups_dir_abs, args.force):
        return 1

    exit_code = 0
    try:
        # Retention deletes old snapshots, so it must only run once the
        # new snapshot is durable and complete - never before, and never
        # if the backup below raised. Running it first (or unconditionally
        # after a failure) would let a failed backup destroy history
        # that a successful one would have covered.
        backup.initiate_backup(
            sources=args.sources,
            backups_dir=backups_dir_abs,
            dry_run=args.dry_run,
            external_rsync=args.external_rsync,
            external_hardlink=args.external_hardlink,
        )
        backup.cleanup_old_backups(backups_dir=backups_dir_abs,
                                   dry_run=args.dry_run)
    except backup.BackupFailedError as err:
        _lg.error("Backup failed: %s", err)
        exit_code = 1
    finally:
        backup.release_backups_lock(backups_dir_abs)

    end_time = time.time()
    spent_time = end_time - start_time
    _lg.info("Finished, time spent: %s", str(timedelta(seconds=spent_time)))

    return exit_code


def _run_restore(args) -> int:
    backups_dir_abs = os.path.abspath(args.backups_dir)
    if not os.path.isdir(backups_dir_abs):
        _lg.error("Backup directory %s does not exist, exiting",
                  args.backups_dir)
        return 1

    dest_abs = os.path.abspath(args.dest)

    # Locked for the same reason a backup is: retention could otherwise
    # delete or quarantine the very snapshot this restore is reading from
    # while it's still in progress. set_backups_lock() already logs why
    # (e.g. "Previous backup is still in progress") - add restore-specific
    # context here so a restore failure doesn't read like a backup one.
    if not backup.set_backups_lock(backups_dir_abs, args.force):
        _lg.error("Could not acquire the backups lock, restore aborted "
                 "(use --force to wait for it instead)")
        return 1

    exit_code = 0
    try:
        try:
            snapshot_entry = backup.find_backup(backups_dir_abs,
                                                args.snapshot_name)
        except backup.BackupFailedError as err:
            _lg.error("%s", err)
            return 1

        _lg.info("Restoring snapshot %s to %s%s",
                 snapshot_entry.name, args.dest,
                 " (dry-run)" if args.dry_run else "")

        if not args.dry_run:
            os.makedirs(dest_abs, exist_ok=True)
        elif not os.path.isdir(dest_abs):
            _lg.warning("Destination %s does not exist (dry-run, not "
                       "creating it)", args.dest)

        try:
            skipped = restore.restore_snapshot(
                snapshot_entry=snapshot_entry,
                dest_dir=dest_abs,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                rel_paths=args.paths or None,
            )
        except restore.RestoreError as err:
            _lg.error("Restore failed: %s", err)
            return 1

        if skipped:
            _lg.warning("Skipped %d existing path(s) (use --overwrite "
                       "always to replace them): %s",
                       len(skipped), ", ".join(skipped))

        if args.verify and not args.dry_run:
            mismatches = restore.verify_restored(
                snapshot_entry=snapshot_entry,
                dest_dir=dest_abs,
                rel_paths=args.paths or None,
            )
            if mismatches:
                _lg.error("Verification failed for %d path(s): %s",
                         len(mismatches), ", ".join(mismatches))
                exit_code = 1
            else:
                _lg.info("Verified: restored content matches the manifest")
    finally:
        backup.release_backups_lock(backups_dir_abs)

    return exit_code


def main():
    formatter = logging.Formatter("{asctime}|{levelname}|{message}", style="{")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    parser = _build_parser()
    args = parser.parse_args(_normalize_argv(sys.argv[1:]))

    loglevel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=loglevel, handlers=[console_handler])

    _lg.info("Starting %s: %s", parser.prog, args)

    if sys.platform not in SUPPORTED_PLATFORMS:
        _lg.error("Not supported platform: %s. Supported platforms: %s",
                  sys.platform, SUPPORTED_PLATFORMS)
        return 1

    if args.command == "restore":
        return _run_restore(args)
    return _run_backup(args)


if __name__ == "__main__":
    sys.exit(main())
