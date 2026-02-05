import os
import os.path
import shutil
import socket
import string
import tempfile

import pytest

from curateipsum import fs


@pytest.fixture
def common_fs_dirs(tmp_path):
    """Create source and destination directories for tests."""
    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "dest"
    src_dir.mkdir()
    dst_dir.mkdir()
    return src_dir, dst_dir


def create_file(parent_dir: str, prefix: str = None) -> str:
    """
    Create a file with random name in parent_dir.
    Returns absolute path to the created file.
    """
    fd, path = tempfile.mkstemp(prefix=prefix, dir=parent_dir)
    with open(fd, "w") as f:
        f.write(string.printable)
    return path


def create_dir(parent_dir: str, prefix: str = None) -> str:
    """
    Create a directory with random name in parent_dir.
    Returns absolute path to created directory.
    """
    return tempfile.mkdtemp(prefix=prefix, dir=parent_dir)


def relpath(full_path: str, src_dir: str, dst_dir: str) -> str:
    """Get a relative path for entity in src/dst dirs."""
    if full_path.startswith(src_dir):
        p_dir = src_dir
    elif full_path.startswith(dst_dir):
        p_dir = dst_dir
    else:
        raise RuntimeError(f"Path {full_path} is not src_dir nor dst_dir")

    return full_path[len(p_dir) + 1 :]


@pytest.fixture
def hardlink_dirs(tmp_path):
    """Create source directory and destination path for hardlink tests."""
    src_dir = str(tmp_path / "source")
    os.mkdir(src_dir)
    dst_dir = src_dir + ".copy"
    yield src_dir, dst_dir
    shutil.rmtree(dst_dir, ignore_errors=True)


def check_directory_stats(d1_path: str, d2_path: str):
    """Check that directory was copied. Fails test, if not."""
    dir1_stat = os.lstat(d1_path)
    dir2_stat = os.lstat(d2_path)

    assert dir1_stat.st_uid == dir2_stat.st_uid
    assert dir1_stat.st_gid == dir2_stat.st_gid
    assert dir1_stat.st_mode == dir2_stat.st_mode
    assert dir1_stat.st_nlink == dir2_stat.st_nlink
    assert dir1_stat.st_size == dir2_stat.st_size
    assert dir1_stat.st_mtime == dir2_stat.st_mtime


class TestHardlinkDir:
    def test_regular_file(self, hardlink_dirs):
        src_dir, dst_dir = hardlink_dirs
        cf_path = create_file(src_dir)
        cf_relpath = relpath(cf_path, src_dir, dst_dir)

        fs.hardlink_dir(src_dir, dst_dir)

        src_stat = os.lstat(cf_path)
        dst_stat = os.lstat(os.path.join(src_dir, cf_relpath))
        assert os.path.samestat(src_stat, dst_stat)
        assert src_stat.st_nlink == 2

    def test_relative_symlink_to_common_file(self, hardlink_dirs):
        src_dir, dst_dir = hardlink_dirs
        cf_relpath = relpath(create_file(src_dir), src_dir, dst_dir)
        sl2cf_relpath = "symlink_to_common_file"
        os.chdir(src_dir)
        os.symlink(cf_relpath, sl2cf_relpath)

        fs.hardlink_dir(src_dir, dst_dir)

        # check the link
        dst_sl2cf_path = os.path.join(dst_dir, sl2cf_relpath)
        assert os.readlink(dst_sl2cf_path) == cf_relpath

        # check stats
        src_stat = os.lstat(os.path.join(dst_dir, sl2cf_relpath))
        dst_stat = os.lstat(dst_sl2cf_path)
        assert os.path.samestat(src_stat, dst_stat)
        assert src_stat.st_nlink == 2

    def test_absolute_symlink_to_common_file(self, hardlink_dirs):
        src_dir, dst_dir = hardlink_dirs
        cf_path = create_file(src_dir)
        sl2cf_relpath = "symlink_to_common_file"
        sl2cf_path = os.path.join(src_dir, sl2cf_relpath)
        os.symlink(cf_path, sl2cf_path)

        fs.hardlink_dir(src_dir, dst_dir)

        # check the link
        dst_sl2cf_path = os.path.join(dst_dir, sl2cf_relpath)
        assert os.readlink(dst_sl2cf_path) == cf_path

        # check stats
        src_stat = os.lstat(os.path.join(dst_dir, sl2cf_relpath))
        dst_stat = os.lstat(dst_sl2cf_path)
        assert os.path.samestat(src_stat, dst_stat)
        assert src_stat.st_nlink == 2

    def test_hardlink_to_common_file(self, hardlink_dirs):
        src_dir, dst_dir = hardlink_dirs
        cf_path = create_file(src_dir)
        hl2cf_relpath = "hardlink_to_common_file"
        hl2cf_path = os.path.join(src_dir, hl2cf_relpath)
        os.link(cf_path, hl2cf_path)

        fs.hardlink_dir(src_dir, dst_dir)

        src_cf_stat = os.lstat(cf_path)
        src_hl_stat = os.lstat(hl2cf_path)
        dst_hl_stat = os.lstat(os.path.join(dst_dir, hl2cf_relpath))

        assert os.path.samestat(src_cf_stat, dst_hl_stat)
        assert os.path.samestat(src_hl_stat, dst_hl_stat)
        assert src_cf_stat.st_nlink == 4

    def test_nested_dir(self, hardlink_dirs):
        src_dir, dst_dir = hardlink_dirs
        src_ndir_path = create_dir(src_dir)
        src_nfile_path = create_file(src_ndir_path)
        ndir_relpath = relpath(src_ndir_path, src_dir, dst_dir)
        nfile_relpath = relpath(src_nfile_path, src_dir, dst_dir)

        fs.hardlink_dir(src_dir, dst_dir)
        check_directory_stats(src_ndir_path,
                              os.path.join(dst_dir, ndir_relpath))

        # check the file in nested directory
        src_fstat = os.lstat(src_nfile_path)
        dst_fstat = os.lstat(os.path.join(dst_dir, nfile_relpath))
        assert os.path.samestat(src_fstat, dst_fstat)
        assert src_fstat.st_nlink == 2


def check_identical_file(f1_path: str, f2_path: str):
    """Check that files are identical. Fails test, if not."""
    st1 = os.lstat(f1_path)
    st2 = os.lstat(f2_path)

    assert st1.st_uid == st2.st_uid
    assert st1.st_gid == st2.st_gid
    assert st1.st_mode == st2.st_mode
    assert st1.st_mtime == st2.st_mtime
    assert st1.st_size == st2.st_size


class TestRsync:
    def test_dst_has_excess_file(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_fpath = create_file(str(dst_dir))

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert not os.path.lexists(dst_fpath)

    def test_dst_has_excess_symlink(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_lpath = os.path.join(str(dst_dir), 'nonexisting_file')
        os.symlink('broken_symlink', dst_lpath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert not os.path.lexists(dst_lpath)

    def test_dst_has_excess_empty_dir(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_dpath = create_dir(str(dst_dir))

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert not os.path.lexists(dst_dpath)

    def test_dst_has_excess_nonempty_dir(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_dpath = create_dir(str(dst_dir))
        create_file(dst_dpath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert not os.path.lexists(dst_dpath)

    def test_dst_has_excess_nonempty_recursive_dir(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_dpath = create_dir(str(dst_dir))
        nested_dpath = create_dir(dst_dpath)
        create_file(nested_dpath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert not os.path.lexists(dst_dpath)

    def test_different_types_src_file_dst_dir(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_fpath = create_file(str(src_dir))
        dst_path = os.path.join(str(dst_dir),
                                relpath(src_fpath, str(src_dir), str(dst_dir)))
        os.mkdir(dst_path)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_path)
        assert os.path.isfile(dst_path)

    def test_different_types_src_file_dst_symlink(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_fpath = create_file(str(src_dir))
        dst_path = os.path.join(str(dst_dir),
                                relpath(src_fpath, str(src_dir), str(dst_dir)))
        os.symlink('broken_link', dst_path)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_path)
        assert os.path.isfile(dst_path)

    def test_different_types_src_symlink_dst_file(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_path = create_file(str(dst_dir))
        src_lpath = os.path.join(str(src_dir),
                                 relpath(dst_path, str(src_dir), str(dst_dir)))
        os.symlink('broken_link', src_lpath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_path)
        assert os.path.islink(dst_path)

    def test_different_types_src_symlink_dst_dir(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        dst_path = create_dir(str(dst_dir))
        src_lpath = os.path.join(str(src_dir),
                                 relpath(dst_path, str(src_dir), str(dst_dir)))
        os.symlink('broken_link', src_lpath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_path)
        assert os.path.islink(dst_path)

    def test_different_types_src_dir_dst_file(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_dpath = create_dir(str(src_dir))
        dst_path = os.path.join(str(dst_dir),
                                relpath(src_dpath, str(src_dir), str(dst_dir)))
        with open(dst_path, "w") as f:
            f.write(string.printable)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_path)
        assert os.path.isdir(dst_path)

    def test_different_types_src_dir_dst_symlink(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_dpath = create_dir(str(src_dir))
        dst_path = os.path.join(str(dst_dir),
                                relpath(src_dpath, str(src_dir), str(dst_dir)))
        os.symlink('broken_link', dst_path)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_path)
        assert os.path.isdir(dst_path)

    def test_src_is_socket(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_spath = create_file(str(src_dir))
        dst_spath = os.path.join(str(dst_dir),
                                 relpath(src_spath, str(src_dir), str(dst_dir)))
        os.unlink(src_spath)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(src_spath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert not os.path.lexists(dst_spath)

    def test_src_dst_same_inode(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_fpath = create_file(str(src_dir))
        dst_fpath = os.path.join(str(dst_dir),
                                 relpath(src_fpath, str(src_dir), str(dst_dir)))
        os.link(src_fpath, dst_fpath)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_fpath)
        src_stat = os.lstat(src_fpath)
        dst_stat = os.lstat(dst_fpath)
        assert src_stat.st_nlink == 1
        assert dst_stat.st_nlink == 1
        assert src_stat.st_ino != dst_stat.st_ino

    def test_src_dst_diff_size(self, common_fs_dirs):
        src_dir, dst_dir = common_fs_dirs
        src_fpath = create_file(str(src_dir))
        dst_fpath = os.path.join(str(dst_dir),
                                 relpath(src_fpath, str(src_dir), str(dst_dir)))
        with open(dst_fpath, "w") as df:
            df.write(string.printable * 2)

        all(fs.rsync(str(src_dir), str(dst_dir)))
        assert os.path.lexists(dst_fpath)
        check_identical_file(src_fpath, dst_fpath)

    # TODO add tests for changing ownership
    # TODO add tests for changing times (?)


class TestCopyFile:
    """Test suite for copy_file function."""

    def test_copy_simple_file(self, tmp_path):
        """Test copying a simple file"""
        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")

        content = b"Hello, World!" * 1000
        with open(src_path, "wb") as f:
            f.write(content)

        fs.copy_file(src_path, dst_path)

        assert os.path.exists(dst_path)
        with open(dst_path, "rb") as f:
            assert f.read() == content

    def test_copy_large_file(self, tmp_path):
        """Test copying a large file (> buffer size)"""
        src_path = os.path.join(str(tmp_path), "large.bin")
        dst_path = os.path.join(str(tmp_path), "large_copy.bin")

        content = b"x" * (200 * 1024)  # 200KB
        with open(src_path, "wb") as f:
            f.write(content)

        fs.copy_file(src_path, dst_path)

        assert os.path.exists(dst_path)
        assert os.path.getsize(dst_path) == len(content)

    def test_copy_preserves_permissions(self, tmp_path):
        """Test that copy_file preserves file permissions"""
        src_path = os.path.join(str(tmp_path), "executable.sh")
        dst_path = os.path.join(str(tmp_path), "executable_copy.sh")

        with open(src_path, "w") as f:
            f.write("#!/bin/bash\necho test")
        os.chmod(src_path, 0o755)

        fs.copy_file(src_path, dst_path)

        src_stat = os.stat(src_path)
        dst_stat = os.stat(dst_path)
        assert src_stat.st_mode == dst_stat.st_mode


class TestCopyDirEntry:
    """Test suite for copy_direntry function."""

    def test_copy_file_entry(self, tmp_path):
        """Test copying a file DirEntry"""
        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")

        with open(src_path, "w") as f:
            f.write("test content")
        os.chmod(src_path, 0o644)

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        assert os.path.isfile(dst_path)
        with open(dst_path, "r") as f:
            assert f.read() == "test content"

    def test_copy_directory_entry(self, tmp_path):
        """Test copying a directory DirEntry"""
        src_path = os.path.join(str(tmp_path), "srcdir")
        dst_path = os.path.join(str(tmp_path), "dstdir")

        os.mkdir(src_path)
        os.chmod(src_path, 0o755)

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        assert os.path.isdir(dst_path)

    def test_copy_symlink_entry(self, tmp_path):
        """Test copying a symlink DirEntry using real os.DirEntry"""
        target_path = os.path.join(str(tmp_path), "target.txt")
        src_link = os.path.join(str(tmp_path), "source_link")
        dst_link = os.path.join(str(tmp_path), "dest_link")

        with open(target_path, "w") as f:
            f.write("target")
        os.symlink(target_path, src_link)

        with os.scandir(str(tmp_path)) as it:
            for entry in it:
                if entry.name == "source_link":
                    fs.copy_direntry(entry, dst_link)
                    break

        assert os.path.islink(dst_link)
        assert os.readlink(dst_link) == target_path


class TestRsyncBasic:
    """Test suite for basic rsync functionality."""

    @pytest.fixture
    def rsync_dirs(self, tmp_path):
        """Create source and destination directories for rsync tests."""
        src_dir = os.path.join(str(tmp_path), "source")
        dst_dir = os.path.join(str(tmp_path), "dest")
        os.mkdir(src_dir)
        return src_dir, dst_dir

    def test_rsync_creates_destination(self, rsync_dirs):
        """Test that rsync creates destination directory if missing"""
        src_dir, dst_dir = rsync_dirs
        assert not os.path.exists(dst_dir)
        list(fs.rsync(src_dir, dst_dir))
        assert os.path.isdir(dst_dir)

    def test_rsync_copies_new_files(self, rsync_dirs):
        """Test that rsync copies new files"""
        src_dir, dst_dir = rsync_dirs
        os.mkdir(dst_dir)

        with open(os.path.join(src_dir, "file1.txt"), "w") as f:
            f.write("content1")
        with open(os.path.join(src_dir, "file2.txt"), "w") as f:
            f.write("content2")

        actions = list(fs.rsync(src_dir, dst_dir))

        assert os.path.exists(os.path.join(dst_dir, "file1.txt"))
        assert os.path.exists(os.path.join(dst_dir, "file2.txt"))

        create_actions = [a for a in actions if a[1] == fs.Actions.CREATE]
        assert len(create_actions) == 2

    def test_rsync_deletes_missing_files(self, rsync_dirs):
        """Test that rsync deletes files not in source"""
        src_dir, dst_dir = rsync_dirs
        os.mkdir(dst_dir)

        dst_file = os.path.join(dst_dir, "old_file.txt")
        with open(dst_file, "w") as f:
            f.write("old content")

        actions = list(fs.rsync(src_dir, dst_dir))

        assert not os.path.exists(dst_file)

        delete_actions = [a for a in actions if a[1] == fs.Actions.DELETE]
        assert len(delete_actions) == 1

    def test_rsync_updates_modified_files(self, rsync_dirs):
        """Test that rsync updates modified files"""
        src_dir, dst_dir = rsync_dirs
        os.mkdir(dst_dir)

        src_file = os.path.join(src_dir, "file.txt")
        dst_file = os.path.join(dst_dir, "file.txt")

        with open(src_file, "w") as f:
            f.write("original")
        with open(dst_file, "w") as f:
            f.write("modified")

        import time
        time.sleep(0.1)
        with open(src_file, "w") as f:
            f.write("updated content")

        actions = list(fs.rsync(src_dir, dst_dir))

        with open(dst_file, "r") as f:
            assert f.read() == "updated content"

        rewrite_actions = [a for a in actions if a[1] == fs.Actions.REWRITE]
        assert len(rewrite_actions) > 0

    def test_rsync_preserves_permissions(self, rsync_dirs):
        """Test that rsync preserves file permissions"""
        src_dir, dst_dir = rsync_dirs
        os.mkdir(dst_dir)

        src_file = os.path.join(src_dir, "script.sh")
        with open(src_file, "w") as f:
            f.write("#!/bin/bash\n")
        os.chmod(src_file, 0o755)

        list(fs.rsync(src_dir, dst_dir))

        dst_file = os.path.join(dst_dir, "script.sh")
        dst_stat = os.stat(dst_file)
        src_stat = os.stat(src_file)
        assert dst_stat.st_mode == src_stat.st_mode


class TestHardlinkDirBasic:
    """Test suite for basic hardlink_dir functionality."""

    @pytest.fixture
    def hardlink_basic_dirs(self, tmp_path):
        """Create source and destination directories for basic hardlink tests."""
        src_dir = os.path.join(str(tmp_path), "source")
        dst_dir = os.path.join(str(tmp_path), "dest")
        os.mkdir(src_dir)
        return src_dir, dst_dir

    def test_hardlink_creates_destination(self, hardlink_basic_dirs):
        """Test that hardlink_dir creates destination directory"""
        src_dir, dst_dir = hardlink_basic_dirs
        result = fs.hardlink_dir(src_dir, dst_dir)
        assert result
        assert os.path.isdir(dst_dir)

    def test_hardlink_links_files(self, hardlink_basic_dirs):
        """Test that files are hardlinked, not copied"""
        src_dir, dst_dir = hardlink_basic_dirs
        src_file = os.path.join(src_dir, "file.txt")
        with open(src_file, "w") as f:
            f.write("test content")

        fs.hardlink_dir(src_dir, dst_dir)

        dst_file = os.path.join(dst_dir, "file.txt")
        assert os.path.exists(dst_file)

        src_stat = os.stat(src_file)
        dst_stat = os.stat(dst_file)
        assert src_stat.st_ino == dst_stat.st_ino

    def test_hardlink_nested_directories(self, hardlink_basic_dirs):
        """Test hardlinking nested directory structure"""
        src_dir, dst_dir = hardlink_basic_dirs
        subdir = os.path.join(src_dir, "subdir")
        os.mkdir(subdir)
        with open(os.path.join(subdir, "nested.txt"), "w") as f:
            f.write("nested content")

        fs.hardlink_dir(src_dir, dst_dir)

        dst_nested = os.path.join(dst_dir, "subdir", "nested.txt")
        assert os.path.exists(dst_nested)

        src_nested = os.path.join(subdir, "nested.txt")
        src_stat = os.stat(src_nested)
        dst_stat = os.stat(dst_nested)
        assert src_stat.st_ino == dst_stat.st_ino


class TestScantree:
    """Test suite for scantree function."""

    def test_scantree_empty_directory(self, tmp_path):
        """Test scanning empty directory"""
        entries = list(fs.scantree(str(tmp_path)))
        assert len(entries) == 0

    def test_scantree_flat_directory(self, tmp_path):
        """Test scanning flat directory structure"""
        for i in range(3):
            with open(os.path.join(str(tmp_path), f"file{i}.txt"), "w") as f:
                f.write(f"content {i}")

        entries = list(fs.scantree(str(tmp_path)))
        assert len(entries) == 3

    def test_scantree_nested_directories(self, tmp_path):
        """Test scanning nested directory structure"""
        subdir1 = os.path.join(str(tmp_path), "dir1")
        subdir2 = os.path.join(subdir1, "dir2")
        os.makedirs(subdir2)

        with open(os.path.join(str(tmp_path), "root.txt"), "w") as f:
            f.write("root")
        with open(os.path.join(subdir1, "sub1.txt"), "w") as f:
            f.write("sub1")
        with open(os.path.join(subdir2, "sub2.txt"), "w") as f:
            f.write("sub2")

        entries = list(fs.scantree(str(tmp_path), dir_first=True))
        assert len(entries) == 5

        names = [os.path.basename(e.path) for e in entries]
        dir1_idx = names.index("dir1")
        sub1_idx = names.index("sub1.txt")
        assert dir1_idx < sub1_idx


class TestRmDirentry:
    """Test suite for rm_direntry function."""

    def test_remove_file(self, tmp_path):
        """Test removing a file"""
        file_path = os.path.join(str(tmp_path), "test.txt")
        with open(file_path, "w") as f:
            f.write("test")

        entry = fs.PseudoDirEntry(file_path)
        fs.rm_direntry(entry)
        assert not os.path.exists(file_path)

    def test_remove_empty_directory(self, tmp_path):
        """Test removing an empty directory"""
        dir_path = os.path.join(str(tmp_path), "testdir")
        os.mkdir(dir_path)

        entry = fs.PseudoDirEntry(dir_path)
        fs.rm_direntry(entry)
        assert not os.path.exists(dir_path)

    def test_remove_directory_with_contents(self, tmp_path):
        """Test removing a directory with files"""
        dir_path = os.path.join(str(tmp_path), "testdir")
        os.mkdir(dir_path)
        with open(os.path.join(dir_path, "file.txt"), "w") as f:
            f.write("test")

        entry = fs.PseudoDirEntry(dir_path)
        fs.rm_direntry(entry)
        assert not os.path.exists(dir_path)

    def test_remove_symlink(self, tmp_path):
        """Test removing a symlink using real os.DirEntry"""
        target = os.path.join(str(tmp_path), "target.txt")
        link = os.path.join(str(tmp_path), "link")

        with open(target, "w") as f:
            f.write("target")
        os.symlink(target, link)

        with os.scandir(str(tmp_path)) as it:
            for entry in it:
                if entry.name == "link":
                    fs.rm_direntry(entry)
                    break

        assert not os.path.exists(link)
        assert not os.path.islink(link)
        assert os.path.exists(target)


class TestPermissionErrors:
    """Test permission error handling during backup operations."""

    @pytest.fixture
    def perm_dirs(self, tmp_path):
        """Create source and destination directories for permission tests."""
        src_dir = os.path.join(str(tmp_path), "source")
        dst_dir = os.path.join(str(tmp_path), "dest")
        os.mkdir(src_dir)
        yield src_dir, dst_dir
        # Restore permissions before cleanup
        for root, dirs, files in os.walk(str(tmp_path)):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o755)
                except:
                    pass
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o644)
                except:
                    pass

    def test_rsync_handles_unreadable_file(self, perm_dirs):
        """Test that rsync handles files it cannot read gracefully."""
        src_dir, dst_dir = perm_dirs
        readable_file = os.path.join(src_dir, "readable.txt")
        with open(readable_file, "w") as f:
            f.write("can read this")

        unreadable_file = os.path.join(src_dir, "unreadable.txt")
        with open(unreadable_file, "w") as f:
            f.write("cannot read this")
        os.chmod(unreadable_file, 0o000)

        try:
            actions = list(fs.rsync(src_dir, dst_dir))

            readable_dst = os.path.join(dst_dir, "readable.txt")
            assert os.path.exists(readable_dst)

            error_actions = [a for a in actions if a[1] == fs.Actions.ERROR]
            assert len(error_actions) > 0, \
                "Should have ERROR action for unreadable file"

        except PermissionError as e:
            pytest.fail(f"rsync crashed on permission error: {e}. "
                       "Should handle gracefully and continue.")

    def test_copy_file_with_unreadable_source(self, perm_dirs):
        """Test copy_file with unreadable source file."""
        src_dir, dst_dir = perm_dirs
        src_file = os.path.join(src_dir, "unreadable.txt")
        dst_file = os.path.join(dst_dir, "copy.txt")

        os.mkdir(dst_dir)
        with open(src_file, "w") as f:
            f.write("test")
        os.chmod(src_file, 0o000)

        with pytest.raises(PermissionError):
            fs.copy_file(src_file, dst_file)

    @pytest.mark.skip(reason="Fails until issue #1 is fixed")
    def test_update_direntry_handles_permission_error(self, perm_dirs):
        """Test that update_direntry handles permission errors gracefully."""
        src_dir, dst_dir = perm_dirs
        src_file = os.path.join(src_dir, "file.txt")
        dst_file = os.path.join(dst_dir, "file.txt")

        os.mkdir(dst_dir)
        with open(src_file, "w") as f:
            f.write("source content")
        with open(dst_file, "w") as f:
            f.write("dest content")

        os.chmod(src_file, 0o000)

        src_entry = fs.PseudoDirEntry(src_file)
        dst_entry = fs.PseudoDirEntry(dst_file)

        try:
            fs.update_direntry(src_entry, dst_entry)
        except PermissionError:
            pytest.fail("update_direntry crashed with PermissionError. "
                       "Should handle gracefully and log error.")

    @pytest.mark.skip(reason="Fails until issue #1 is fixed")
    def test_nest_hardlink_handles_permission_error(self, perm_dirs):
        """Test that nest_hardlink handles permission errors gracefully."""
        src_dir, dst_dir = perm_dirs
        subdir = os.path.join(src_dir, "subdir")
        os.mkdir(subdir)
        src_file = os.path.join(subdir, "file.txt")
        with open(src_file, "w") as f:
            f.write("test")

        delta_dir = os.path.join(dst_dir, ".backup_delta")
        os.mkdir(dst_dir)
        os.mkdir(delta_dir)
        os.chmod(delta_dir, 0o555)

        try:
            fs.nest_hardlink(src_dir, "subdir/file.txt", delta_dir)
        except PermissionError:
            pytest.fail("nest_hardlink crashed with PermissionError. "
                       "Should handle gracefully and log error.")
