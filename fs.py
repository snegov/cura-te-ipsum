import logging
import os
import subprocess
from typing import Iterable


def rsync_ext(src, dst, dry_run=False):
    """Call external rsync command"""
    rsync_args = ["rsync"]
    if dry_run:
        rsync_args.append("-n")
    rsync_args.append("-a")  # archive
    rsync_args.append("-z")  # compress
    rsync_args.append("-h")  # human-readable
    rsync_args.append("-v")  # verbose
    rsync_args.append("-u")  # don't touch new files on receiver
    rsync_args.append("--progress")
    rsync_args.append("--del")  # delete during
    rsync_args.append(src)
    rsync_args.append(dst)
    res = subprocess.run(rsync_args)
    return res


def scantree(path) -> Iterable[os.DirEntry]:
    """Recursively yield DirEntry file objects for given directory."""
    entry: os.DirEntry
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry.path)
        else:
            yield entry


def rsync(src_dir, dst_dir=None):
    """
    Do sync
    :param src_dir: source dir
    :param dst_dir: dest dir, create if not exists
    :return: nothing
    """

    logging.info(f"Rsync: {src_dir} -> {dst_dir}")
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_abs):
        raise RuntimeError(f"Error during reading source directory: {src_abs}")
    if os.path.exists(dst_abs):
        if not os.path.isdir(dst_abs):
            raise RuntimeError(f"Destination path is not a directory: {dst_abs}")
    else:
        os.mkdir(dst_abs)

    for src_entry in scantree(src_abs):
        rel_path = src_entry.path.removeprefix(src_abs + "/")
        dst_path = os.path.join(dst_abs, rel_path)
        src_stat = os.lstat(src_entry.path)
        dst_stat = os.lstat(dst_path)

        do_update = False
        # check file size
        if src_stat.st_size != dst_stat.st_size:
            do_update = True
        # check modification time (mtime)
        if src_stat.st_mtime > dst_stat.st_mtime:
            do_update = True

        if do_update:
            logging.info("Updating %s", src_entry)


def hardlink_dir(src_dir, dst_dir):
    """
    Make hardlink for a directory with all its content.
    :param src_dir: path to source directory
    :param dst_dir: path to target directory
    :return: None
    """
    logging.info(f"Recursive hardlinking: {src_dir} -> {dst_dir}")
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    def recursive_hardlink(src, dst):
        logging.debug(f"Creating directory: {src} -> {dst}")
        os.mkdir(dst)

        with os.scandir(src) as it:
            ent: os.DirEntry
            for ent in it:
                ent_dst_path = os.path.join(dst, ent.name)
                if ent.is_dir(follow_symlinks=False):
                    recursive_hardlink(ent.path, ent_dst_path)
                    continue
                if ent.is_file(follow_symlinks=False) or ent.is_symlink():
                    logging.debug(f"Hardlink file: {ent.path} -> {ent_dst_path}")
                    os.link(ent.path, ent_dst_path, follow_symlinks=False)
                    continue
                # something that is not a file, symlink or directory
                raise NotImplementedError(ent.path)

    if not os.path.isdir(src_abs):
        logging.error(f"Error reading source directory: {src_dir}")
        raise RuntimeError(f"Error reading source directory: {src_dir}")

    if os.path.exists(dst_abs):
        logging.error(f"Destination already exists: {dst_dir}")
        raise RuntimeError(f"Destination already exists: {dst_dir}")

    recursive_hardlink(src_abs, dst_abs)
    return
