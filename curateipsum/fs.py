"""
Module with filesystem-related functions.
"""

import enum
import glob
import logging
import os
import subprocess
import sys
import uuid
from typing import Iterable, Tuple, Union

_lg = logging.getLogger(__name__)


class BackupCreationError(Exception):
    pass


class Actions(enum.Enum):
    NOTHING = enum.auto()
    DELETE = enum.auto()
    REWRITE = enum.auto()
    UPDATE_TIME = enum.auto()
    UPDATE_PERM = enum.auto()
    UPDATE_OWNER = enum.auto()
    CREATE = enum.auto()
    ERROR = enum.auto()


class PseudoDirEntry:
    """
    Duck-typed os.DirEntry for paths that don't exist yet or when you need
    DirEntry-like interface for arbitrary paths.

    Problem: os.DirEntry is created by os.scandir() and cannot be manually
    constructed. But we need DirEntry-compatible objects for:
    - Paths that will exist soon (new backup directories)
    - Constructed paths (marker files)
    - Uniform interface in functions accepting both real and future entries

    Why not just use strings? Functions like rm_direntry(), copy_direntry()
    accept Union[os.DirEntry, PseudoDirEntry] and call .is_dir(), .stat()
    methods. Using this class avoids branching on type throughout the codebase.

    Why not pathlib.Path? We heavily use os.scandir() which returns DirEntry
    objects with cached stat info. PseudoDirEntry maintains API consistency
    with minimal overhead.

    Example usage:
        # Create entry for future backup directory
        cur_backup = PseudoDirEntry("/backups/20260204_120000")
        os.mkdir(cur_backup.path)
        set_backup_marker(cur_backup)  # accepts DirEntry-like object

    Caches stat results like real DirEntry to avoid repeated syscalls.
    """
    def __init__(self, path):
        # Use abspath, not realpath - realpath resolves symlinks
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path)
        self._is_dir = None
        self._is_file = None
        self._is_symlink = None
        # Cache both stat and lstat separately
        self._stat_follow = None
        self._stat_nofollow = None

    def __str__(self):
        return self.name

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        if follow_symlinks:
            if self._is_dir is None:
                self._is_dir = os.path.isdir(self.path)
            return self._is_dir
        else:
            # When not following symlinks, must return False if path is symlink
            return os.path.isdir(self.path) and not os.path.islink(self.path)

    def is_file(self, follow_symlinks: bool = True) -> bool:
        if follow_symlinks:
            if self._is_file is None:
                self._is_file = os.path.isfile(self.path)
            return self._is_file
        else:
            # When not following symlinks, must return False if path is symlink
            return os.path.isfile(self.path) and not os.path.islink(self.path)

    def is_symlink(self) -> bool:
        if self._is_symlink is None:
            self._is_symlink = os.path.islink(self.path)
        return self._is_symlink

    def stat(self, follow_symlinks: bool = True):
        if follow_symlinks:
            if self._stat_follow is None:
                self._stat_follow = os.stat(self.path)
            return self._stat_follow
        else:
            if self._stat_nofollow is None:
                self._stat_nofollow = os.lstat(self.path)
            return self._stat_nofollow


def _parse_rsync_output(line: str) -> Tuple[str, Actions, str]:
    action = None
    change_string, relpath = line.split(' ', maxsplit=1)
    if change_string == "*deleting":
        return relpath, Actions.DELETE, ""

    update_type = change_string[0]
    entity_type = change_string[1]
    change_type = change_string[2:]

    if update_type == "c" and entity_type in {"d", "L"} and "+" in change_type:
        action = Actions.CREATE
    elif update_type == ">" and entity_type == "f" and "+" in change_type:
        action = Actions.CREATE
    elif entity_type == "f" and ("s" in change_type or "t" in change_type):
        action = Actions.REWRITE
    elif entity_type == "d" and "t" in change_type:
        action = Actions.UPDATE_TIME
    elif "p" in change_type:
        action = Actions.UPDATE_PERM
    elif "o" in change_type or "g" in change_type:
        action = Actions.UPDATE_OWNER

    if action is None:
        raise RuntimeError("Not parsed string: %s" % line)
    return relpath, action, ""


def rsync_ext(src, dst, dry_run=False) -> Iterable[Tuple[str, Actions, str]]:
    """
    Call external rsync command for syncing files from src to dst.
    Yield (path, action, error message) tuples.
    """
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
    process = subprocess.Popen(rsync_args,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
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
    """
    Recursively yield DirEntry objects (dir/file/symlink) for given directory.
    """
    entry: os.DirEntry
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


def rm_direntry(entry: Union[os.DirEntry, PseudoDirEntry]):
    """ Recursively delete DirEntry (dir/file/symlink). """
    if entry.is_file(follow_symlinks=False) or entry.is_symlink():
        os.unlink(entry.path)
    elif entry.is_dir(follow_symlinks=False):
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
    fin = None
    fout = None
    try:
        fin = os.open(src, READ_FLAGS)
        fstat = os.fstat(fin)
        fout = os.open(dst, WRITE_FLAGS, fstat.st_mode)
        for x in iter(lambda: os.read(fin, BUFFER_SIZE), b""):
            os.write(fout, x)
    finally:
        if fout is not None:
            try:
                os.close(fout)
            except OSError:
                pass
        if fin is not None:
            try:
                os.close(fin)
            except OSError:
                pass


def _break_shared_hardlink(path: str):
    """
    Give `path` a private inode if it currently shares one with another
    file (nlink > 1), so a subsequent in-place metadata change (chmod,
    chown, utime, flags) can never mutate that other file. Files copied
    into a staging directory via hardlink_dir() start out hardlinked to
    the previous snapshot; this is the copy-on-write step that keeps
    that previous, completed snapshot immutable.

    The break itself must be metadata-neutral: copy_file() only carries
    over the mode at file-creation time, not ownership or timestamps, so
    the new private copy is explicitly restored to the original's full
    stat before it replaces `path` - otherwise a caller that only meant
    to update permissions would silently also reset ownership/mtime as a
    side effect of this implementation detail.
    """
    st = os.lstat(path)
    if st.st_nlink <= 1:
        return
    tmp_path = "%s.cow-%d-%s" % (path, os.getpid(), uuid.uuid4().hex[:8])
    try:
        copy_file(path, tmp_path)
        try:
            os.chown(tmp_path, st.st_uid, st.st_gid)
        except PermissionError:
            _lg.debug("Cannot preserve ownership while breaking hardlink "
                      "(not root): %s", path)
        os.chmod(tmp_path, st.st_mode)
        os.utime(tmp_path, (st.st_atime, st.st_mtime))
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def copy_direntry(entry: Union[os.DirEntry, PseudoDirEntry], dst_path):
    """ Non-recursive DirEntry (file/dir/symlink) copy. """
    src_stat = entry.stat(follow_symlinks=False)
    # Classify with lstat semantics and check symlink-ness first: is_dir()
    # (and is_file()) default to follow_symlinks=True, so a symlink
    # pointing at a directory would otherwise be misclassified as a
    # directory here and get an empty directory created in its place,
    # silently losing the symlink and its target.
    if entry.is_symlink():
        link_target = os.readlink(entry.path)
        os.symlink(link_target, dst_path)

    elif entry.is_dir(follow_symlinks=False):
        os.mkdir(dst_path)

    else:
        copy_file(entry.path, dst_path)

    if entry.is_symlink():
        # change symlink attributes only if supported by OS
        if os.chown in os.supports_follow_symlinks:
            try:
                os.chown(dst_path, src_stat.st_uid, src_stat.st_gid,
                         follow_symlinks=False)
            except PermissionError:
                _lg.debug("Cannot change ownership (not root): %s", dst_path)
        if os.chmod in os.supports_follow_symlinks:
            os.chmod(dst_path, src_stat.st_mode, follow_symlinks=False)
        if os.utime in os.supports_follow_symlinks:
            os.utime(dst_path, (src_stat.st_atime, src_stat.st_mtime),
                     follow_symlinks=False)
    else:
        try:
            os.chown(dst_path, src_stat.st_uid, src_stat.st_gid)
        except PermissionError:
            _lg.debug("Cannot change ownership (not root): %s", dst_path)
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


def rsync(src_dir,
          dst_dir,
          dry_run=False) -> Iterable[Tuple[str, Actions, str]]:
    """
    Sync files/dirs/symlinks from src_dir to dst_dir.
    Yield (path, action, error message) tuples.
    Entries in dst_dir will be removed if not present in src_dir.
    Analog of 'rsync --delete -irltpog'.
    """

    _lg.debug("Rsync: %s -> %s", src_dir, dst_dir)
    src_root_abs = os.path.abspath(src_dir)
    dst_root_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_root_abs):
        raise BackupCreationError(
            "Error during reading source directory: %s" % src_root_abs
        )
    if os.path.exists(dst_root_abs):
        if not os.path.isdir(dst_root_abs):
            raise BackupCreationError(
                "Destination path is not a directory: %s" % dst_root_abs
            )
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
            _lg.debug("Rsync, deleting: %s", rel_path)
            try:
                rm_direntry(dst_entry)
                yield rel_path, Actions.DELETE, ""
                continue
            except OSError as exc:
                raise BackupCreationError(exc) from exc

        # mark src entry as taken for processing
        del src_files_map[rel_path]

        src_entry: os.DirEntry
        # rewrite dst if it has different type from src
        if src_entry.is_file(follow_symlinks=False):
            if not dst_entry.is_file(follow_symlinks=False):
                _lg.debug("Rsync, rewriting"
                          " (src is a file, dst is not a file): %s",
                          rel_path)
                try:
                    update_direntry(src_entry, dst_entry)
                    yield rel_path, Actions.REWRITE, ""
                except OSError as exc:
                    yield rel_path, Actions.ERROR, str(exc)
                continue

        if src_entry.is_dir(follow_symlinks=False):
            if not dst_entry.is_dir(follow_symlinks=False):
                _lg.debug("Rsync, rewriting"
                          " (src is a dir, dst is not a dir): %s",
                          rel_path)
                try:
                    update_direntry(src_entry, dst_entry)
                    yield rel_path, Actions.REWRITE, ""
                except OSError as exc:
                    yield rel_path, Actions.ERROR, str(exc)
                continue

        if src_entry.is_symlink():
            if not dst_entry.is_symlink():
                _lg.debug("Rsync, rewriting"
                          " (src is a symlink, dst is not a symlink): %s",
                          rel_path)
                try:
                    update_direntry(src_entry, dst_entry)
                    yield rel_path, Actions.REWRITE, ""
                except OSError as exc:
                    yield rel_path, Actions.ERROR, str(exc)
                continue

        # rewrite dst if it is hard link to src (bad for backups)
        if src_entry.inode() == dst_entry.inode():
            _lg.debug("Rsync, rewriting (different inodes): %s", rel_path)
            try:
                update_direntry(src_entry, dst_entry)
                yield rel_path, Actions.REWRITE, ""
            except OSError as exc:
                yield rel_path, Actions.ERROR, str(exc)
            continue

        src_stat = src_entry.stat(follow_symlinks=False)
        dst_stat = dst_entry.stat(follow_symlinks=False)

        # rewrite dst file/symlink which have different size or mtime than src
        if src_entry.is_file(follow_symlinks=False):
            same_size = src_stat.st_size == dst_stat.st_size
            same_mtime = src_stat.st_mtime == dst_stat.st_mtime
            if not (same_size and same_mtime):
                reason = "size" if not same_size else "time"
                _lg.debug("Rsync, rewriting (different %s): %s",
                          reason, rel_path)
                try:
                    update_direntry(src_entry, dst_entry)
                    yield rel_path, Actions.REWRITE, ""
                except OSError as exc:
                    yield rel_path, Actions.ERROR, str(exc)
                continue

        # rewrite dst symlink if it points somewhere else than src
        if src_entry.is_symlink():
            if os.readlink(src_entry.path) != os.readlink(dst_entry.path):
                _lg.debug("Rsync, rewriting (different symlink target): %s",
                          rel_path)
                try:
                    update_direntry(src_entry, dst_entry)
                    yield rel_path, Actions.REWRITE, ""
                except OSError as exc:
                    yield rel_path, Actions.ERROR, str(exc)
                continue

        # Symlinks reaching here already have a matching target (handled
        # above), and applying chmod/chown to a symlink path without
        # follow_symlinks=False support would silently modify whatever
        # the symlink points to - including a target outside the backup
        # entirely. There's nothing meaningful left to sync for them.
        if src_entry.is_symlink():
            continue

        # A regular file reaching here is unchanged in content, but may
        # still be hardlinked to the same file in the previous, supposedly
        # immutable snapshot (hardlink_dir() links unchanged files in at
        # the start of every backup to save space). Break that link
        # before mutating permissions/ownership in place, or the change
        # would silently apply to every older snapshot sharing the inode.
        if src_entry.is_file(follow_symlinks=False):
            if src_stat.st_mode != dst_stat.st_mode or (
                    src_stat.st_uid != dst_stat.st_uid
                    or src_stat.st_gid != dst_stat.st_gid):
                _break_shared_hardlink(dst_entry.path)

        # update permissions and ownership
        if src_stat.st_mode != dst_stat.st_mode:
            _lg.debug("Rsync, updating permissions: %s", rel_path)
            os.chmod(dst_entry.path, src_stat.st_mode)
            yield rel_path, Actions.UPDATE_PERM, ""

        if (src_stat.st_uid != dst_stat.st_uid
                or src_stat.st_gid != dst_stat.st_gid):
            _lg.debug("Rsync, updating owners: %s", rel_path)
            try:
                os.chown(dst_entry.path, src_stat.st_uid, src_stat.st_gid)
                yield rel_path, Actions.UPDATE_OWNER, ""
            except PermissionError:
                _lg.debug("Cannot change ownership (not root): %s", rel_path)

    # process remained source entries (new files/dirs/symlinks)
    for rel_path, src_entry in src_files_map.items():
        dst_path = os.path.join(dst_root_abs, rel_path)
        _lg.debug("Rsync, creating: %s", rel_path)
        try:
            copy_direntry(src_entry, dst_path)
            yield rel_path, Actions.CREATE, ""
        except OSError as exc:
            yield rel_path, Actions.ERROR, str(exc)

    # restore dir mtimes in dst, updated by updating files
    for src_entry in scantree(src_root_abs, dir_first=True):
        if not src_entry.is_dir(follow_symlinks=False):
            continue
        rel_path = src_entry.path[len(src_root_abs) + 1:]
        dst_path = os.path.join(dst_root_abs, rel_path)
        src_stat = src_entry.stat(follow_symlinks=False)
        dst_stat = os.lstat(dst_path)
        if src_stat.st_mtime != dst_stat.st_mtime:
            _lg.debug("Rsync, restoring directory mtime: %s", dst_path)
            os.utime(dst_path,
                     (src_stat.st_atime, src_stat.st_mtime),
                     follow_symlinks=False)

    # restore dst_root dir mtime
    src_root_stat = os.lstat(src_root_abs)
    dst_root_stat = os.lstat(dst_root_abs)
    if src_root_stat.st_mtime != dst_root_stat.st_mtime:
        _lg.debug("Rsync, restoring root directory mtime: %s", dst_root_abs)
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
    process = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
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
    :return: True if success, False otherwise.
    """
    with os.scandir(src) as it:
        ent: os.DirEntry
        for ent in it:
            ent_dst_path = os.path.join(dst, ent.name)
            if ent.is_dir(follow_symlinks=False):
                _lg.debug("Hardlink, copying directory: %s -> %s",
                          ent.path, ent_dst_path)
                os.mkdir(ent_dst_path)

                # process directory children
                _recursive_hardlink(ent.path, ent_dst_path)

                # save directory's metainfo
                ent_stat = ent.stat(follow_symlinks=False)
                try:
                    os.chown(ent_dst_path, ent_stat.st_uid, ent_stat.st_gid)
                except PermissionError:
                    _lg.debug("Cannot change ownership (not root): %s", ent_dst_path)
                os.chmod(ent_dst_path, ent_stat.st_mode)
                os.utime(ent_dst_path, (ent_stat.st_atime, ent_stat.st_mtime))

                continue
            if ent.is_file(follow_symlinks=False) or ent.is_symlink():
                _lg.debug("Hardlink, creating link for file: %s -> %s",
                          ent.path, ent_dst_path)
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
    :return: True if success, False otherwise.
    """
    _lg.debug("Recursive hardlinking: %s -> %s", src_dir, dst_dir)
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    if not os.path.isdir(src_abs):
        raise RuntimeError(f"Error reading source directory: {src_dir}")
    if os.path.exists(dst_abs):
        raise RuntimeError(f"Destination already exists: {dst_dir}")
    _lg.debug("Hardlink, creating directory: %s", dst_abs)
    os.mkdir(dst_abs)

    hardlink_func = (_recursive_hardlink_ext if use_external
                     else _recursive_hardlink)
    return hardlink_func(src_abs, dst_abs)


def nest_hardlink(src_dir: str, src_relpath: str, dst_dir: str):
    """
    Hardlink entity from (src_dir + src_relpath) to dst_dir preserving dir
    structure of src_relpath.
    """
    _lg.debug("Nested hardlinking: %s%s%s -> %s",
              src_dir, os.path.sep, src_relpath, dst_dir)
    if os.path.isabs(src_relpath) or os.path.pardir in src_relpath.split(
            os.path.sep):
        raise RuntimeError(
            "Refusing non-normalized relative path: %s" % src_relpath)

    src_dir_abs = os.path.abspath(src_dir)
    src_full_path = os.path.join(src_dir_abs, src_relpath)
    dst_dir_abs = os.path.abspath(dst_dir)
    dst_full_path = os.path.join(dst_dir_abs, src_relpath)

    # check source entity and destination directory
    if not os.path.lexists(src_full_path):
        raise RuntimeError("Error reading source entity: %s" % src_full_path)
    if os.path.lexists(dst_dir_abs):
        if not os.path.isdir(dst_dir_abs):
            raise RuntimeError("Destination path is not a directory: %s"
                               % dst_dir_abs)
    else:
        os.mkdir(dst_dir_abs)

    # if destination entity exists, check it points to source entity
    dst_entry = PseudoDirEntry(dst_full_path)
    if os.path.lexists(dst_entry.path):
        src_stat = os.lstat(src_full_path)
        if os.path.samestat(src_stat, dst_entry.stat()):
            return
        # remove otherwise
        rm_direntry(dst_entry)

    src_cur_path = src_dir_abs
    dst_cur_path = dst_dir_abs
    for rel_part in src_relpath.split(sep=os.path.sep):
        src_cur_path = os.path.join(src_cur_path, rel_part)
        dst_cur_path = os.path.join(dst_cur_path, rel_part)
        if os.path.exists(dst_cur_path):
            continue
        copy_direntry(PseudoDirEntry(src_cur_path), dst_cur_path)
