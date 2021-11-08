"""
Module with filesystem-related functions.
"""

import enum
import glob
import logging
import os
import subprocess
import sys
from typing import Iterable, Tuple

_lg = logging.getLogger(__name__)


class Actions(enum.Enum):
    nothing = enum.auto()
    delete = enum.auto()
    rewrite = enum.auto()
    update_time = enum.auto()
    update_perm = enum.auto()
    update_owner = enum.auto()
    create = enum.auto()

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


def _parse_rsync_output(line: str) -> Tuple[str, Actions]:
    action = None
    change_string, relpath = line.split(' ', maxsplit=1)
    if change_string == "*deleting":
        return relpath, Actions.delete

    update_type = change_string[0]
    entity_type = change_string[1]
    change_type = change_string[2:]

    if update_type == "c" and entity_type in {"d", "L"} and "+" in change_type:
        action = Actions.create
    elif update_type == ">" and entity_type == "f" and "+" in change_type:
        action = Actions.create
    elif entity_type == "f" and ("s" in change_type or "t" in change_type):
        action = Actions.rewrite
    elif entity_type == "d" and "t" in change_type:
        action = Actions.update_time
    elif "p" in change_type:
        action = Actions.update_perm
    elif "o" in change_type or "g" in change_type:
        action = Actions.update_owner

    if action is None:
        raise RuntimeError("Not parsed string: %s" % line)
    return relpath, action


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
    process = subprocess.Popen(rsync_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with process.stdout:
        prev_line = None
        for line in iter(process.stdout.readline, b""):
            _lg.debug("Rsync current line: %s", line)
            if prev_line is None:
                prev_line = line
                continue

            try:
                prev_line = prev_line.decode("utf-8").strip()
            # some issues with cyrillic in filenames
            except UnicodeDecodeError:
                _lg.error("Can't process rsync line: %s", prev_line)
                continue
            _lg.debug("Rsync itemize line: %s", prev_line)
            yield _parse_rsync_output(prev_line)
            prev_line = line

        try:
            prev_line = prev_line.decode("utf-8").strip()
            _lg.debug("Rsync itemize line: %s", prev_line)
            yield _parse_rsync_output(prev_line)
        # some issues with cyrillic in filenames
        except UnicodeDecodeError:
            _lg.error("Can't process rsync line: %s", prev_line)

    process.wait()


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


def copy_entity(src_path: str, dst_path: str):
    """ Non-recursive fs entity (file, dir or symlink) copy. """
    src_stat = os.lstat(src_path)
    is_symlink = os.path.islink(src_path)

    if os.path.isdir(src_path):
        os.mkdir(dst_path)

    elif is_symlink:
        link_target = os.readlink(src_path)
        os.symlink(link_target, dst_path)

    else:
        copy_file(src_path, dst_path)

    if is_symlink:
        # change symlink attributes only if supported by OS
        if os.chown in os.supports_follow_symlinks:
            os.chown(dst_path, src_stat.st_uid, src_stat.st_gid,
                     follow_symlinks=False)
        if os.chmod in os.supports_follow_symlinks:
            os.chmod(dst_path, src_stat.st_mode, follow_symlinks=False)
        if os.utime in os.supports_follow_symlinks:
            os.utime(dst_path, (src_stat.st_atime, src_stat.st_mtime),
                     follow_symlinks=False)
    else:
        os.chown(dst_path, src_stat.st_uid, src_stat.st_gid)
        os.chmod(dst_path, src_stat.st_mode)
        os.utime(dst_path, (src_stat.st_atime, src_stat.st_mtime))


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
    if entry.is_symlink():
        # change symlink attributes only if supported by OS
        if os.chown in os.supports_follow_symlinks:
            os.chown(dst_path, src_stat.st_uid, src_stat.st_gid,
                     follow_symlinks=False)
        if os.chmod in os.supports_follow_symlinks:
            os.chmod(dst_path, src_stat.st_mode, follow_symlinks=False)
        if os.utime in os.supports_follow_symlinks:
            os.utime(dst_path, (src_stat.st_atime, src_stat.st_mtime),
                     follow_symlinks=False)
    else:
        os.chown(dst_path, src_stat.st_uid, src_stat.st_gid)
        os.chmod(dst_path, src_stat.st_mode)
        os.utime(dst_path, (src_stat.st_atime, src_stat.st_mtime))


def update_direntry(src_entry: os.DirEntry, dst_entry: os.DirEntry):
    """
    Make dst DirEntry (file/dir/symlink) same as src.
    If dst is directory, its content will be removed.
    Src dir content will not be copied into dst dir.
    """
    rm_direntry(dst_entry)
    copy_direntry(src_entry, dst_entry.path)


def rsync(src_dir, dst_dir, dry_run=False) -> Iterable[tuple]:
    """
    Do sync
    :param src_dir: source dir
    :param dst_dir: dest dir, create if not exists
    :param dry_run: not used
    :return: nothing
    """

    _lg.debug("Rsync: %s -> %s", src_dir, dst_dir)
    src_root_abs = os.path.abspath(src_dir)
    dst_root_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_root_abs):
        raise RuntimeError(f"Error during reading source directory: {src_root_abs}")
    if os.path.exists(dst_root_abs):
        if not os.path.isdir(dst_root_abs):
            raise RuntimeError("Destination path is not a directory: %s" % dst_root_abs)
    else:
        os.mkdir(dst_root_abs)

    # Create source map {rel_path: dir_entry}
    src_files_map = {
        ent.path[len(src_root_abs) + 1:]: ent for ent in scantree(src_root_abs)
    }

    # process dst tree
    for dst_entry in scantree(dst_root_abs, dir_first=False):
        rel_path = dst_entry.path[len(dst_root_abs) + 1:]

        src_entry = src_files_map.get(rel_path)

        # remove dst entries not existing in source
        if src_entry is None:
            _lg.debug("Deleting: %s", rel_path)
            rm_direntry(dst_entry)
            yield rel_path, Actions.delete
            continue

        # mark src entry as taken for processing
        del src_files_map[rel_path]

        src_entry: os.DirEntry
        # rewrite dst if it has different than src type
        if src_entry.is_file(follow_symlinks=False):
            if not dst_entry.is_file(follow_symlinks=False):
                _lg.debug("Rewriting (src is a file, dst is not a file): %s", rel_path)
                update_direntry(src_entry, dst_entry)
                yield rel_path, Actions.rewrite
                continue
        if src_entry.is_dir(follow_symlinks=False):
            if not dst_entry.is_dir(follow_symlinks=False):
                _lg.debug("Rewriting (src is a dir, dst is not a dir): %s", rel_path)
                update_direntry(src_entry, dst_entry)
                yield rel_path, Actions.rewrite
                continue
        if src_entry.is_symlink():
            if not dst_entry.is_symlink():
                _lg.debug("Rewriting (src is a symlink, dst is not a symlink): %s", rel_path)
                update_direntry(src_entry, dst_entry)
                yield rel_path, Actions.rewrite
                continue

        # rewrite dst if it is hard link to src (bad for backups)
        if src_entry.inode() == dst_entry.inode():
            _lg.debug("Rewriting (different inodes): %s", rel_path)
            update_direntry(src_entry, dst_entry)
            yield rel_path, Actions.rewrite
            continue

        src_stat = src_entry.stat(follow_symlinks=False)
        dst_stat = dst_entry.stat(follow_symlinks=False)

        # rewrite dst file/symlink which have different with src size or mtime
        if src_entry.is_file(follow_symlinks=False):
            same_size = src_stat.st_size == dst_stat.st_size
            same_mtime = src_stat.st_mtime == dst_stat.st_mtime
            if not (same_size and same_mtime):
                reason = "size" if not same_size else "time"
                _lg.debug("Rewriting (different %s): %s", reason, rel_path)
                update_direntry(src_entry, dst_entry)
                yield rel_path, Actions.rewrite
                continue

        # rewrite dst symlink if it points somewhere else than src
        if src_entry.is_symlink():
            if os.readlink(src_entry.path) != os.readlink(dst_entry.path):
                _lg.debug("Rewriting (different symlink target): %s", rel_path)
                update_direntry(src_entry, dst_entry)
                continue

        # update permissions and ownership
        if src_stat.st_mode != dst_stat.st_mode:
            _lg.debug("Updating permissions: %s", rel_path)
            yield rel_path, Actions.update_perm
            os.chmod(dst_entry.path, dst_stat.st_mode)

        if src_stat.st_uid != dst_stat.st_uid or src_stat.st_gid != dst_stat.st_gid:
            _lg.debug("Updating owners: %s", rel_path)
            yield rel_path, Actions.update_owner
            os.chown(dst_entry.path, src_stat.st_uid, src_stat.st_gid)

    # process remained source entries
    for rel_path, src_entry in src_files_map.items():
        dst_path = os.path.join(dst_root_abs, rel_path)
        _lg.debug("Creating: %s", rel_path)
        copy_direntry(src_entry, dst_path)
        yield rel_path, Actions.create

    # restore dir mtimes in dst, updated by updating files
    for src_entry in scantree(src_root_abs, dir_first=True):
        if not src_entry.is_dir():
            continue
        rel_path = src_entry.path[len(src_root_abs) + 1:]
        dst_path = os.path.join(dst_root_abs, rel_path)
        src_stat = src_entry.stat(follow_symlinks=False)
        dst_stat = os.lstat(dst_path)
        if src_stat.st_mtime != dst_stat.st_mtime:
            _lg.debug("Restoring directory mtime: %s", dst_path)
            os.utime(dst_path,
                     (src_stat.st_atime, src_stat.st_mtime),
                     follow_symlinks=False)

    # restore dst_root dir mtime
    src_root_stat = os.lstat(src_root_abs)
    dst_root_stat = os.lstat(dst_root_abs)
    if src_root_stat.st_mtime != dst_root_stat.st_mtime:
        _lg.debug("Restoring root directory mtime: %s", src_root_abs)
        os.utime(dst_root_abs,
                 (src_root_stat.st_atime, src_root_stat.st_mtime),
                 follow_symlinks=False)


def _recursive_hardlink_ext(src: str, dst: str) -> bool:
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
            _lg.debug("%s: %s", cp, line.decode("utf-8").strip())
    exitcode = process.wait()
    return not bool(exitcode)


def _recursive_hardlink(src: str, dst: str) -> bool:
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
                _lg.debug("Copying directory: %s -> %s", ent.path, ent_dst_path)
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
                _lg.debug("Hardlink file: %s -> %s", ent.path, ent_dst_path)
                os.link(ent.path, ent_dst_path, follow_symlinks=False)
                continue
            # something that is not a file, symlink or directory
            raise NotImplementedError(ent.path)

    return True


def hardlink_dir(src_dir, dst_dir, use_external: bool = False) -> bool:
    """
    Make hardlink for a directory with all its content.
    :param src_dir: path to source directory
    :param dst_dir: path to target directory
    :param use_external: whether to use external cp -al command
    :return: success or not
    """
    _lg.debug("Recursive hardlinking: %s -> %s", src_dir, dst_dir)
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_abs):
        raise RuntimeError(f"Error reading source directory: {src_dir}")
    if os.path.exists(dst_abs):
        raise RuntimeError(f"Destination already exists: {dst_dir}")
    _lg.debug("Creating directory: %s", dst_abs)
    os.mkdir(dst_abs)

    hardlink_func = _recursive_hardlink_ext if use_external else _recursive_hardlink
    return hardlink_func(src_abs, dst_abs)


def nest_hardlink(src_dir: str, src_relpath: str, dst_dir: str):
    """
    Hardlink entity from (src_dir + src_relpath) to dst_dir preserving dir structure.
    """
    _lg.debug("Nested hardlinking: %s/%s -> %s", src_dir, src_relpath, dst_dir)
    src_dir_abs = os.path.abspath(src_dir)
    src_full_path = os.path.join(src_dir_abs, src_relpath)
    dst_dir_abs = os.path.abspath(dst_dir)
    dst_full_path = os.path.join(dst_dir_abs, src_relpath)

    # check source entity and destination directory
    if not os.path.exists(src_full_path):
        raise RuntimeError(f"Error reading source entity: {src_full_path}")
    if os.path.exists(dst_dir_abs):
        if not os.path.isdir(dst_dir_abs):
            raise RuntimeError("Destination path is not a directory: %s" % dst_dir_abs)
    else:
        os.mkdir(dst_dir_abs)

    # if destination entity exists, check it points to source entity
    if os.path.exists(dst_full_path):
        src_stat = os.lstat(src_full_path)
        if os.path.samestat(src_stat, os.lstat(dst_full_path)):
            return
        # remove otherwise
        os.unlink(dst_full_path)

    src_cur_path = src_dir_abs
    dst_cur_path = dst_dir_abs
    for rel_part in src_relpath.split(sep=os.path.sep):
        src_cur_path = os.path.join(src_cur_path, rel_part)
        dst_cur_path = os.path.join(dst_cur_path, rel_part)
        if os.path.exists(dst_cur_path):
            continue
        copy_entity(src_cur_path, dst_cur_path)
