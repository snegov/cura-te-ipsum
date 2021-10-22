"""
Module with filesystem-related functions.
"""

import enum
import glob
import logging
import os
import subprocess
import sys
from typing import Iterable

_lg = logging.getLogger(__name__)


# *deleting will_be_deleted
# >f.st.... .gitignore
# >f+++++++ LICENSE
# >f+++++++ LICENSE-sym
# >f+++++++ README.md
# >f+++++++ find_stale_torrents.py
# >f+++++++ rootfile
# cL+++++++ test -> rootfile
# cd+++++++ folder/
# >f+++++++ folder/in-folder
# cd+++++++ java-alg/


def rsync_ext(src, dst, dry_run=False):
    """Call external rsync command"""
    rsync_args = ["rsync"]
    if dry_run:
        rsync_args.append("--dry-run")
    rsync_args.append("--archive")
    # rsync_args.append("--compress")
    # rsync_args.append("--inplace")
    rsync_args.append("--whole-file")
    rsync_args.append("--human-readable")
    rsync_args.append("--delete-during")
    rsync_args.append("--itemize-changes")
    rsync_args.append(f"{src}/")
    rsync_args.append(str(dst))

    _lg.info("Executing external command: %s", " ".join(rsync_args))
    res = subprocess.run(rsync_args)
    return res


def scantree(path, dir_first=True) -> Iterable[os.DirEntry]:
    """Recursively yield DirEntry file objects for given directory."""
    entry: os.DirEntry
    """Recursively yield DirEntry objects for given directory."""
    with os.scandir(path) as scan_it:
        for entry in scan_it:
            if entry.is_dir(follow_symlinks=False):
                if dir_first:
                    yield entry
                yield from scantree(entry.path, dir_first)
                if not dir_first:
                    yield entry
            else:
                yield entry


def rm_direntry(entry: os.DirEntry):
    """ Recursively delete DirEntry (dir, file or symlink). """
    if entry.is_file(follow_symlinks=False) or entry.is_symlink():
        os.unlink(entry.path)
        return
    if entry.is_dir(follow_symlinks=False):
        with os.scandir(entry.path) as it:
            child_entry: os.DirEntry
            for child_entry in it:
                rm_direntry(child_entry)
        os.rmdir(entry.path)


try:
    O_BINARY = os.O_BINARY  # Windows only
except AttributeError:
    O_BINARY = 0
READ_FLAGS = os.O_RDONLY | O_BINARY
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | O_BINARY
BUFFER_SIZE = 128 * 1024


def copy_file(src, dst):
    """ Copy file from src to dst. Faster than shutil.copy. """
    try:
        fin = os.open(src, READ_FLAGS)
        stat = os.fstat(fin)
        fout = os.open(dst, WRITE_FLAGS, stat.st_mode)
        for x in iter(lambda: os.read(fin, BUFFER_SIZE), b""):
            os.write(fout, x)
    finally:
        try: os.close(fout)
        except: pass
        try: os.close(fin)
        except: pass


def copy_direntry(entry: os.DirEntry, dst_path):
    """ Non-recursive DirEntry (file, dir or symlink) copy. """
    if entry.is_dir():
        os.mkdir(dst_path)

    elif entry.is_symlink():
        link_target = os.readlink(entry.path)
        os.symlink(link_target, dst_path)

    else:
        copy_file(entry.path, dst_path)

    src_stat = entry.stat(follow_symlinks=False)
    os.chown(dst_path, src_stat.st_uid, src_stat.st_gid, follow_symlinks=False)
    os.chmod(dst_path, src_stat.st_mode, follow_symlinks=False)
    os.utime(dst_path, (src_stat.st_atime, src_stat.st_mtime), follow_symlinks=False)


def update_direntry(src_entry: os.DirEntry, dst_entry: os.DirEntry):
    """
    Make dst DirEntry (file/dir/symlink) same as src.
    If dst is directory, its content will be removed.
    Src dir content will not be copied into dst dir.
    """
    rm_direntry(dst_entry)
    copy_direntry(src_entry, dst_entry.path)


class Actions(enum.Enum):
    nothing = enum.auto()
    delete = enum.auto()
    rewrite = enum.auto()
    update_perm = enum.auto()
    update_owner = enum.auto()
    create = enum.auto()


def rsync(src_dir, dst_dir, dry_run=False):
    """
    Do sync
    :param src_dir: source dir
    :param dst_dir: dest dir, create if not exists
    :return: nothing
    """

    _lg.info(f"Rsync: {src_dir} -> {dst_dir}")
    src_root_abs = os.path.abspath(src_dir)
    dst_root_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_root_abs):
        raise RuntimeError(f"Error during reading source directory: {src_root_abs}")
    if os.path.exists(dst_root_abs):
        if not os.path.isdir(dst_root_abs):
            raise RuntimeError(f"Destination path is not a directory: {dst_root_abs}")
    else:
        os.mkdir(dst_root_abs)

    # {rel_path: dir_entry} map
    src_files_map = {
        ent.path[len(src_root_abs) + 1:]: ent for ent in scantree(src_root_abs)
    }

    # process dst tree
    for dst_entry in scantree(dst_root_abs, dir_first=False):
        rel_path = dst_entry.path[len(dst_root_abs) + 1:]

        src_entry = src_files_map.get(rel_path)

        # remove dst entries not existing in source
        if src_entry is None:
            _lg.info("deleting %s", rel_path)
            rm_direntry(dst_entry)
            continue

        # mark src entry as taken for processing
        del src_files_map[rel_path]

        src_entry: os.DirEntry
        # rewrite dst if it has different than src type
        if src_entry.is_file(follow_symlinks=False):
            if not dst_entry.is_file(follow_symlinks=False):
                _lg.info("rewriting %s", rel_path)
                update_direntry(src_entry, dst_entry)
                continue
        if src_entry.is_dir(follow_symlinks=False):
            if not dst_entry.is_dir(follow_symlinks=False):
                _lg.info("rewriting %s", rel_path)
                update_direntry(src_entry, dst_entry)
                continue
        if src_entry.is_symlink():
            if not dst_entry.is_symlink():
                _lg.info("rewriting %s", rel_path)
                update_direntry(src_entry, dst_entry)
                continue

        # rewrite dst if it is hard link to src (bad for backups)
        if src_entry.inode() == dst_entry.inode():
            _lg.info("rewriting %s", rel_path)
            update_direntry(src_entry, dst_entry)
            continue

        src_stat = src_entry.stat(follow_symlinks=False)
        dst_stat = dst_entry.stat(follow_symlinks=False)

        # rewrite dst file/symlink which have different with src size or mtime
        if src_entry.is_file(follow_symlinks=False):
            same_size = src_stat.st_size == dst_stat.st_size
            same_mtime = src_stat.st_mtime == dst_stat.st_mtime
            if not (same_size and same_mtime):
                _lg.info("rewriting %s", rel_path)
                update_direntry(src_entry, dst_entry)
                continue

        # rewrite dst symlink if it points somewhere else than src
        if src_entry.is_symlink():
            if os.readlink(src_entry.path) != os.readlink(dst_entry.path):
                _lg.info("rewriting %s", rel_path)
                update_direntry(src_entry, dst_entry)
                continue

        # update permissions and ownership
        if src_stat.st_mode != dst_stat.st_mode:
            _lg.info("updating permissions %s", rel_path)
            os.chmod(dst_entry.path, dst_stat.st_mode)

        if src_stat.st_uid != dst_stat.st_uid or src_stat.st_gid != dst_stat.st_gid:
            _lg.info("updating owners %s", rel_path)
            os.chown(dst_entry.path, src_stat.st_uid, src_stat.st_gid)

    # process remained source entries
    for rel_path, src_entry in src_files_map.items():
        dst_path = os.path.join(dst_root_abs, rel_path)
        _lg.info("creating %s", rel_path)
        copy_direntry(src_entry, dst_path)

    # restore dir mtimes in dst, updated by updating files
    for src_entry in scantree(src_root_abs, dir_first=True):
        if not src_entry.is_dir():
            continue
        rel_path = src_entry.path[len(src_root_abs) + 1:]
        dst_path = os.path.join(dst_root_abs, rel_path)
        src_stat = src_entry.stat(follow_symlinks=False)
        os.utime(dst_path,
                 (src_stat.st_atime, src_stat.st_mtime),
                 follow_symlinks=False)

    # restore dst_root dir mtime
    src_root_stat = os.lstat(src_root_abs)
    os.utime(dst_root_abs,
             (src_root_stat.st_atime, src_root_stat.st_mtime),
             follow_symlinks=False)


def _hardlink_dir_ext(src, dst) -> bool:
    """
    Make hardlink for a directory using cp -al. Both src and dst should exist.
    :param src: absolute path to source directory.
    :param dst: absolute path to target directory.
    :return: success or not
    """
    if sys.platform == "darwin":
        cp = "gcp"
    else:
        cp = "cp"
    src_content = glob.glob(f"{src}/*")
    cmd = [cp, "--archive", "--verbose", "--link", *src_content, dst]
    _lg.info("Executing external command: %s", " ".join(cmd))
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with process.stdout:
        for line in iter(process.stdout.readline, b""):
            logging.debug("%s: %s", cp, line.decode("utf-8").strip())
    exitcode = process.wait()
    return not bool(exitcode)


def _recursive_hardlink(src, dst) -> bool:
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

                # process directory children
                _recursive_hardlink(ent.path, ent_dst_path)

                # save directory's metainfo
                ent_stat = ent.stat(follow_symlinks=False)
                os.chown(ent_dst_path, ent_stat.st_uid, ent_stat.st_gid)
                os.chmod(ent_dst_path, ent_stat.st_mode)
                os.utime(ent_dst_path, (ent_stat.st_atime, ent_stat.st_mtime))

                continue
            if ent.is_file(follow_symlinks=False) or ent.is_symlink():
                _lg.debug(f"Hardlink file: {ent.path} -> {ent_dst_path}")
                os.link(ent.path, ent_dst_path, follow_symlinks=False)
                continue
            # something that is not a file, symlink or directory
            raise NotImplementedError(ent.path)

    return True


def hardlink_dir(src_dir, dst_dir) -> bool:
    """
    Make hardlink for a directory with all its content.
    :param src_dir: path to source directory
    :param dst_dir: path to target directory
    :return: success or not
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

    return _recursive_hardlink(src_abs, dst_abs)
