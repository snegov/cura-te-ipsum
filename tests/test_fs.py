import os
import os.path
import shutil

import pytest

from curateipsum import fs
from conftest import create_file, create_dir, relpath


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
        original_cwd = os.getcwd()
        try:
            os.chdir(src_dir)
            os.symlink(cf_relpath, sl2cf_relpath)
        finally:
            os.chdir(original_cwd)

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

    def test_returns_sha256_of_content(self, tmp_path):
        """copy_file returns the sha256 hex digest of the copied bytes"""
        import hashlib
        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")
        content = b"some content to hash"
        with open(src_path, "wb") as f:
            f.write(content)

        digest = fs.copy_file(src_path, dst_path)

        assert digest == hashlib.sha256(content).hexdigest()

    def test_detects_source_truncated_during_copy(self, tmp_path):
        """
        A source file whose size changes between the read loop starting
        and finishing (detected via fstat on the same descriptor) must
        raise, not silently produce a truncated/inconsistent copy.
        """
        from unittest import mock

        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")
        with open(src_path, "wb") as f:
            f.write(b"x" * 1000)

        real_read = os.read
        call_count = {"n": 0}

        def read_then_truncate(fd, n):
            call_count["n"] += 1
            data = real_read(fd, n)
            if call_count["n"] == 1:
                os.truncate(src_path, 10)
            return data

        with mock.patch("os.read", side_effect=read_then_truncate):
            with pytest.raises(fs.BackupCreationError):
                fs.copy_file(src_path, dst_path)

    def test_partial_write_is_completed(self, tmp_path):
        """os.write() may write fewer bytes than given; copy_file must
        loop until everything requested has actually been written."""
        from unittest import mock

        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")
        content = b"y" * 5000
        with open(src_path, "wb") as f:
            f.write(content)

        real_write = os.write
        with mock.patch("os.write",
                        side_effect=lambda fd, data: real_write(
                            fd, bytes(data)[:1])):
            fs.copy_file(src_path, dst_path)

        with open(dst_path, "rb") as f:
            assert f.read() == content


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

    def test_copy_file_preserves_times(self, tmp_path):
        """Test that file timestamps are preserved"""
        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")

        with open(src_path, "w") as f:
            f.write("test content")

        # set specific timestamps: atime=1000000000, mtime=2000000000
        os.utime(src_path, (1000000000, 2000000000))

        # capture original times before copy (copy will update src atime)
        orig_stat = os.lstat(src_path)

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        dst_stat = os.lstat(dst_path)
        assert dst_stat.st_atime == orig_stat.st_atime
        assert dst_stat.st_mtime == orig_stat.st_mtime

    def test_copy_file_preserves_permissions(self, tmp_path):
        """Test that file permissions are preserved"""
        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")

        with open(src_path, "w") as f:
            f.write("test content")
        os.chmod(src_path, 0o600)

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        src_stat = os.lstat(src_path)
        dst_stat = os.lstat(dst_path)
        assert dst_stat.st_mode == src_stat.st_mode

    def test_copy_file_preserves_nanosecond_mtime(self, tmp_path):
        """README documents nanosecond mtime precision for the Python
        backend; whole-second os.utime() calls can't catch a backend
        that silently truncates to second resolution, so this sets a
        sub-second mtime explicitly."""
        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")

        with open(src_path, "w") as f:
            f.write("test content")
        os.utime(src_path, ns=(1_000_000_000_123456789,
                                2_000_000_000_987654321))

        src_stat = os.lstat(src_path)
        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        dst_stat = os.lstat(dst_path)
        assert dst_stat.st_mtime_ns == src_stat.st_mtime_ns
        assert dst_stat.st_atime_ns == src_stat.st_atime_ns

    def test_copy_directory_preserves_times(self, tmp_path):
        """Test that directory timestamps are preserved"""
        src_path = os.path.join(str(tmp_path), "srcdir")
        dst_path = os.path.join(str(tmp_path), "dstdir")

        os.mkdir(src_path)
        # set specific timestamps
        os.utime(src_path, (1000000000, 2000000000))

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        src_stat = os.lstat(src_path)
        dst_stat = os.lstat(dst_path)
        assert dst_stat.st_atime == src_stat.st_atime
        assert dst_stat.st_mtime == src_stat.st_mtime

    def test_copy_directory_preserves_permissions(self, tmp_path):
        """Test that directory permissions are preserved"""
        src_path = os.path.join(str(tmp_path), "srcdir")
        dst_path = os.path.join(str(tmp_path), "dstdir")

        os.mkdir(src_path)
        os.chmod(src_path, 0o700)

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        src_stat = os.lstat(src_path)
        dst_stat = os.lstat(dst_path)
        assert dst_stat.st_mode == src_stat.st_mode

    def test_copy_symlink_to_directory_stays_a_symlink(self, tmp_path):
        """
        Regression: is_dir()/is_file() default to follow_symlinks=True,
        so a symlink pointing at a directory must be classified via
        is_symlink() first, or it gets misclassified as a directory and
        an empty real directory is created in its place - silently
        destroying the symlink and losing its target entirely.
        """
        target_dir = os.path.join(str(tmp_path), "target_dir")
        src_link = os.path.join(str(tmp_path), "source_link")
        dst_link = os.path.join(str(tmp_path), "dest_link")

        os.mkdir(target_dir)
        with open(os.path.join(target_dir, "canary"), "w") as f:
            f.write("content")
        os.symlink(target_dir, src_link)

        with os.scandir(str(tmp_path)) as it:
            for entry in it:
                if entry.name == "source_link":
                    fs.copy_direntry(entry, dst_link)
                    break

        assert os.path.islink(dst_link)
        assert os.readlink(dst_link) == target_dir

    def test_copy_symlink_preserves_times_if_supported(self, tmp_path):
        """Test that symlink timestamps are preserved (OS-dependent)"""
        target_path = os.path.join(str(tmp_path), "target.txt")
        src_link = os.path.join(str(tmp_path), "source_link")
        dst_link = os.path.join(str(tmp_path), "dest_link")

        with open(target_path, "w") as f:
            f.write("target")
        os.symlink(target_path, src_link)

        # set symlink timestamps if supported
        if os.utime in os.supports_follow_symlinks:
            os.utime(src_link, (1000000000, 2000000000),
                     follow_symlinks=False)
            # capture original times before copy
            orig_stat = os.lstat(src_link)

        # find the real os.DirEntry for the symlink
        entry = None
        with os.scandir(str(tmp_path)) as it:
            for e in it:
                if e.name == "source_link":
                    entry = e
                    break

        fs.copy_direntry(entry, dst_link)

        if os.utime in os.supports_follow_symlinks:
            dst_stat = os.lstat(dst_link)
            assert dst_stat.st_atime == orig_stat.st_atime
            assert dst_stat.st_mtime == orig_stat.st_mtime
        else:
            # just verify the symlink was created
            assert os.path.islink(dst_link)

    def test_copy_symlink_preserves_nanosecond_mtime_if_supported(
            self, tmp_path):
        """Same nanosecond-precision claim as
        test_copy_file_preserves_nanosecond_mtime(), but for the
        follow_symlinks=False code path in copy_direntry()."""
        target_path = os.path.join(str(tmp_path), "target.txt")
        src_link = os.path.join(str(tmp_path), "source_link")
        dst_link = os.path.join(str(tmp_path), "dest_link")

        with open(target_path, "w") as f:
            f.write("target")
        os.symlink(target_path, src_link)

        if os.utime not in os.supports_follow_symlinks:
            pytest.skip("OS doesn't support setting symlink timestamps")

        os.utime(src_link, ns=(1_000_000_000_123456789,
                                2_000_000_000_987654321),
                 follow_symlinks=False)
        orig_stat = os.lstat(src_link)

        entry = None
        with os.scandir(str(tmp_path)) as it:
            for e in it:
                if e.name == "source_link":
                    entry = e
                    break

        fs.copy_direntry(entry, dst_link)

        dst_stat = os.lstat(dst_link)
        assert dst_stat.st_mtime_ns == orig_stat.st_mtime_ns
        assert dst_stat.st_atime_ns == orig_stat.st_atime_ns

    def test_copy_file_preserves_ownership_if_root(self, tmp_path):
        """Test that file ownership is preserved (requires root)"""
        if os.geteuid() != 0:
            pytest.skip("Ownership tests require root privileges")

        src_path = os.path.join(str(tmp_path), "source.txt")
        dst_path = os.path.join(str(tmp_path), "dest.txt")

        with open(src_path, "w") as f:
            f.write("test content")

        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        src_stat = os.lstat(src_path)
        dst_stat = os.lstat(dst_path)
        assert dst_stat.st_uid == src_stat.st_uid
        assert dst_stat.st_gid == src_stat.st_gid


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

    def test_one_filesystem_default_crosses_mount_points(self, tmp_path,
                                                          monkeypatch):
        """Without one_filesystem, a simulated mount point is descended."""
        mount_dir = tmp_path / "mount"
        mount_dir.mkdir()
        (mount_dir / "other_fs_file.txt").write_text("content")

        real_lstat = os.lstat

        def fake_lstat(path, *args, **kwargs):
            st = real_lstat(path, *args, **kwargs)
            if os.path.abspath(path) == str(mount_dir):
                fields = list(st)
                fields[2] = st.st_dev + 1  # st_dev
                st = os.stat_result(fields)
            return st

        monkeypatch.setattr(os, "lstat", fake_lstat)

        entries = list(fs.scantree(str(tmp_path)))
        names = [os.path.basename(e.path) for e in entries]
        assert "other_fs_file.txt" in names

    def test_one_filesystem_excludes_mount_point_contents(self, tmp_path,
                                                           monkeypatch):
        """With one_filesystem, a mount point's contents are excluded."""
        mount_dir = tmp_path / "mount"
        mount_dir.mkdir()
        (mount_dir / "other_fs_file.txt").write_text("content")

        real_lstat = os.lstat

        def fake_lstat(path, *args, **kwargs):
            st = real_lstat(path, *args, **kwargs)
            if os.path.abspath(path) == str(mount_dir):
                fields = list(st)
                fields[2] = st.st_dev + 1  # st_dev
                st = os.stat_result(fields)
            return st

        monkeypatch.setattr(os, "lstat", fake_lstat)

        entries = list(fs.scantree(str(tmp_path), one_filesystem=True))
        names = [os.path.basename(e.path) for e in entries]

        # the mount point directory itself is still present...
        assert "mount" in names
        # ...but its contents are excluded
        assert "other_fs_file.txt" not in names

    def test_one_filesystem_root_via_symlink(self, tmp_path):
        """A symlinked walk root must use the target's device, not its
        own - scandir() follows the symlink to list real subdirectories,
        which must not appear to be on a different device than the root."""
        real_root = tmp_path / "real_root"
        real_root.mkdir()
        subdir = real_root / "dir1"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")

        link_root = tmp_path / "link_root"
        link_root.symlink_to(real_root)

        entries = list(fs.scantree(str(link_root), one_filesystem=True))
        names = [os.path.basename(e.path) for e in entries]
        assert "dir1" in names
        assert "file.txt" in names

    def test_one_filesystem_same_device_unaffected(self, tmp_path):
        """With one_filesystem, a same-device tree is fully scanned."""
        subdir = tmp_path / "dir1"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")

        entries = list(fs.scantree(str(tmp_path), one_filesystem=True))
        names = [os.path.basename(e.path) for e in entries]
        assert "dir1" in names
        assert "file.txt" in names


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


