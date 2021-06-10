"""
Module with filesystem-related functions.
"""

import logging
import os
import subprocess
from typing import Iterable

_lg = logging.getLogger(__name__)


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
            yield entry
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

    _lg.info(f"Rsync: {src_dir} -> {dst_dir}")
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
        rel_path = src_entry.path[len(src_abs)+1:]
        dst_path = os.path.join(dst_abs, rel_path)
        src_stat = src_entry.stat(follow_symlinks=False)

        dst_stat = os.lstat(dst_path)

        if src_entry.is_dir(follow_symlinks=False):
            pass

        do_update = False
        # check file size
        if src_stat.st_size != dst_stat.st_size:
            do_update = True
        # check modification time (mtime)
        if src_stat.st_mtime > dst_stat.st_mtime:
            do_update = True

        if do_update:
            _lg.info("Updating %s", src_entry)


def _hardlink_dir_ext(src, dst):
    """
    Make hardlink for a directory using cp -al. Both src and dst should exist.
    :param src: absolute path to source directory.
    :param dst: absolute path to target directory.
    :return: None
    """
    res = subprocess.run(["cp", "-v", "-a", "-l", f"{src}/*", dst])
    return res


def _recursive_hardlink(src, dst):
    """
    Do hardlink directory recursively using python only.
    Both src and dst directories should exist.
    :param src: absolute path to source directory.
    :param dst: absolute path to target directory.
    :return: None
    """
    with os.scandir(src) as it:
        ent: os.DirEntry
        for ent in it:
            ent_dst_path = os.path.join(dst, ent.name)
            if ent.is_dir(follow_symlinks=False):
                _lg.debug(f"Copying directory: {ent.path} -> {ent_dst_path}")
                os.mkdir(ent_dst_path)
                ent_stat = ent.stat(follow_symlinks=False)
                os.chown(ent_dst_path, ent_stat.st_uid, ent_stat.st_gid)
                os.chmod(ent_dst_path, ent_stat.st_mode)

                # process directory children
                _recursive_hardlink(ent.path, ent_dst_path)
                continue
            if ent.is_file(follow_symlinks=False) or ent.is_symlink():
                _lg.debug(f"Hardlink file: {ent.path} -> {ent_dst_path}")
                os.link(ent.path, ent_dst_path, follow_symlinks=False)
                continue
            # something that is not a file, symlink or directory
            raise NotImplementedError(ent.path)


def hardlink_dir(src_dir, dst_dir):
    """
    Make hardlink for a directory with all its content.
    :param src_dir: path to source directory
    :param dst_dir: path to target directory
    :return: None
    """
    _lg.info(f"Recursive hardlinking: {src_dir} -> {dst_dir}")
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_abs):
        _lg.error(f"Error reading source directory: {src_dir}")
        raise RuntimeError(f"Error reading source directory: {src_dir}")

    if os.path.exists(dst_abs):
        _lg.error(f"Destination already exists: {dst_dir}")
        raise RuntimeError(f"Destination already exists: {dst_dir}")

    _lg.debug(f"Creating directory: {dst_abs}")
    os.mkdir(dst_abs)
    _recursive_hardlink(src_abs, dst_abs)
    return
