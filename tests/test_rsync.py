import os
import os.path
import socket
import string
from unittest.mock import Mock, patch

import pytest

from curateipsum import fs
from conftest import create_file, create_dir, relpath, check_identical_file


class MockStdout:
    """Mock stdout that supports context manager and readline iteration."""

    def __init__(self, lines):
        self.lines = iter(lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def readline(self):
        try:
            return next(self.lines)
        except StopIteration:
            return b""


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

    def test_broken_symlink_in_source(self, common_fs_dirs):
        """Test that rsync copies broken symlinks correctly."""
        src_dir, dst_dir = common_fs_dirs
        src_lpath = os.path.join(str(src_dir), 'broken_link')
        # create symlink pointing to non-existent target
        os.symlink('/nonexistent/target/file.txt', src_lpath)
        dst_lpath = os.path.join(str(dst_dir), 'broken_link')

        all(fs.rsync(str(src_dir), str(dst_dir)))

        # verify symlink was copied and remains broken
        assert os.path.islink(dst_lpath)
        assert os.readlink(dst_lpath) == '/nonexistent/target/file.txt'
        assert not os.path.exists(dst_lpath)  # link target doesn't exist

    def test_unicode_filename(self, common_fs_dirs):
        """Test that rsync handles unicode characters in filenames."""
        src_dir, dst_dir = common_fs_dirs
        # use various unicode characters: emoji, cyrillic, chinese, accents
        unicode_name = 'test_文件_файл_café_🎉.txt'
        src_fpath = os.path.join(str(src_dir), unicode_name)
        with open(src_fpath, "w", encoding='utf-8') as f:
            f.write("unicode content: 你好世界")
        dst_fpath = os.path.join(str(dst_dir), unicode_name)

        all(fs.rsync(str(src_dir), str(dst_dir)))

        assert os.path.exists(dst_fpath)
        with open(dst_fpath, "r", encoding='utf-8') as f:
            assert f.read() == "unicode content: 你好世界"

    def test_filename_with_spaces(self, common_fs_dirs):
        """Test that rsync handles filenames with spaces."""
        src_dir, dst_dir = common_fs_dirs
        spaced_name = 'file with many   spaces.txt'
        src_fpath = os.path.join(str(src_dir), spaced_name)
        with open(src_fpath, "w") as f:
            f.write("spaced content")
        dst_fpath = os.path.join(str(dst_dir), spaced_name)

        all(fs.rsync(str(src_dir), str(dst_dir)))

        assert os.path.exists(dst_fpath)
        check_identical_file(src_fpath, dst_fpath)

    def test_empty_file(self, common_fs_dirs):
        """Test that rsync handles empty (0 byte) files correctly."""
        src_dir, dst_dir = common_fs_dirs
        src_fpath = os.path.join(str(src_dir), 'empty.txt')
        # create empty file
        open(src_fpath, "w").close()
        dst_fpath = os.path.join(str(dst_dir), 'empty.txt')

        all(fs.rsync(str(src_dir), str(dst_dir)))

        assert os.path.exists(dst_fpath)
        assert os.path.getsize(dst_fpath) == 0

    def test_very_long_relative_path(self, common_fs_dirs):
        """Test that rsync handles deeply nested directory structures."""
        src_dir, dst_dir = common_fs_dirs
        # create a deeply nested path (10 levels deep)
        nested_path = os.path.join(*[f"level{i}" for i in range(10)])
        src_nested = os.path.join(str(src_dir), nested_path)
        os.makedirs(src_nested, exist_ok=True)

        # create a file in the deepest directory
        src_fpath = os.path.join(src_nested, 'deep_file.txt')
        with open(src_fpath, "w") as f:
            f.write("deeply nested content")

        dst_nested = os.path.join(str(dst_dir), nested_path)
        dst_fpath = os.path.join(dst_nested, 'deep_file.txt')

        all(fs.rsync(str(src_dir), str(dst_dir)))

        assert os.path.exists(dst_fpath)
        check_identical_file(src_fpath, dst_fpath)


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


class TestParseRsyncOutput:
    """Test _parse_rsync_output() parsing of rsync --itemize-changes."""

    def test_delete_file(self):
        """Parse deletion output."""
        result = fs._parse_rsync_output("*deleting path/to/file.txt")
        assert result == ("path/to/file.txt", fs.Actions.DELETE, "")

    def test_delete_nested_path(self):
        """Parse deletion with nested directory structure."""
        result = fs._parse_rsync_output("*deleting deeply/nested/dir/file.md")
        assert result == ("deeply/nested/dir/file.md", fs.Actions.DELETE, "")

    def test_create_file(self):
        """Parse file creation."""
        result = fs._parse_rsync_output(">f+++++++++ new_file.txt")
        assert result == ("new_file.txt", fs.Actions.CREATE, "")

    def test_create_file_nested(self):
        """Parse file creation in subdirectory."""
        result = fs._parse_rsync_output(">f+++++++++ subdir/another.log")
        assert result == ("subdir/another.log", fs.Actions.CREATE, "")

    def test_create_directory(self):
        """Parse directory creation."""
        result = fs._parse_rsync_output("cd+++++++++ new_directory/")
        assert result == ("new_directory/", fs.Actions.CREATE, "")

    def test_create_symlink(self):
        """Parse symlink creation."""
        result = fs._parse_rsync_output("cL+++++++++ link_to_file")
        assert result == ("link_to_file", fs.Actions.CREATE, "")

    def test_rewrite_file_size_change(self):
        """Parse file rewrite due to size change."""
        result = fs._parse_rsync_output(">f.s...... modified_file.txt")
        assert result == ("modified_file.txt", fs.Actions.REWRITE, "")

    def test_rewrite_file_time_change(self):
        """Parse file rewrite due to time change."""
        result = fs._parse_rsync_output(">f..t...... touched_file.dat")
        assert result == ("touched_file.dat", fs.Actions.REWRITE, "")

    def test_rewrite_file_size_and_time(self):
        """Parse file rewrite due to both size and time change."""
        result = fs._parse_rsync_output(">f.st...... changed.bin")
        assert result == ("changed.bin", fs.Actions.REWRITE, "")

    def test_update_directory_time(self):
        """Parse directory time update."""
        result = fs._parse_rsync_output(">d..t...... some_dir/")
        assert result == ("some_dir/", fs.Actions.UPDATE_TIME, "")

    def test_update_permissions(self):
        """Parse permission change."""
        result = fs._parse_rsync_output(">f....p.... executable.sh")
        assert result == ("executable.sh", fs.Actions.UPDATE_PERM, "")

    def test_update_permissions_with_time_change(self):
        """Time change takes precedence over permission change."""
        result = fs._parse_rsync_output(">f...tp.... script.py")
        assert result == ("script.py", fs.Actions.REWRITE, "")

    def test_update_owner(self):
        """Parse owner change."""
        result = fs._parse_rsync_output(">f.....o... owned_file.txt")
        assert result == ("owned_file.txt", fs.Actions.UPDATE_OWNER, "")

    def test_update_group(self):
        """Parse group change."""
        result = fs._parse_rsync_output(">f......g.. grouped_file.txt")
        assert result == ("grouped_file.txt", fs.Actions.UPDATE_OWNER, "")

    def test_update_owner_and_group(self):
        """Parse both owner and group change."""
        result = fs._parse_rsync_output(">f.....og.. shared_file.txt")
        assert result == ("shared_file.txt", fs.Actions.UPDATE_OWNER, "")

    def test_invalid_format_raises_error(self):
        """Unparseable line should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Not parsed string"):
            fs._parse_rsync_output(">f......... unknown.txt")

    def test_empty_change_string_raises_error(self):
        """Empty change indicators should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Not parsed string"):
            fs._parse_rsync_output(">f......... no_action.txt")


class TestRsyncExt:
    """Test external rsync command wrapper."""

    def test_command_construction(self, tmp_path):
        """Verify rsync command is built with correct arguments."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            # minimal valid rsync output
            mock_process.stdout = MockStdout([b">f+++++++++ test.txt\n"])
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            list(fs.rsync_ext(str(src), str(dst)))

            # verify command was called with correct arguments
            args = mock_popen.call_args[0][0]
            assert args[0] == "rsync"
            assert "--archive" in args
            assert "--whole-file" in args
            assert "--human-readable" in args
            assert "--delete-during" in args
            assert "--itemize-changes" in args
            assert args[-2] == f"{src}/"
            assert args[-1] == str(dst)

    def test_dry_run_flag(self, tmp_path):
        """Verify --dry-run flag is added when dry_run=True."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout([b">f+++++++++ test.txt\n"])
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            list(fs.rsync_ext(str(src), str(dst), dry_run=True))

            args = mock_popen.call_args[0][0]
            assert "--dry-run" in args

    def test_processes_rsync_output_lines(self, tmp_path):
        """Parse valid rsync itemize output lines."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        rsync_output = [
            b"cd+++++++++ subdir/\n",
            b">f+++++++++ subdir/newfile.txt\n",
        ]

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout(rsync_output)
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            results = list(fs.rsync_ext(str(src), str(dst)))

            # both lines should be processed
            assert len(results) == 2
            assert results[0][0] == "subdir/"
            assert results[0][1] == fs.Actions.CREATE
            assert results[1][0] == "subdir/newfile.txt"
            assert results[1][1] == fs.Actions.CREATE

    def test_handles_unicode_decode_error(self, tmp_path, caplog):
        """Log error when encountering non-UTF8 bytes."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        # invalid UTF-8 byte sequence
        invalid_utf8 = b"\xff\xfe invalid bytes\n"
        rsync_output = [
            invalid_utf8,
            b">f+++++++++ validfile.txt\n",
        ]

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout(rsync_output)
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            results = list(fs.rsync_ext(str(src), str(dst)))

            # current behavior: invalid line causes prev_line to get stuck,
            # so subsequent lines are also skipped (potential bug)
            assert len(results) == 0
            assert "Can't process rsync line" in caplog.text

    def test_yields_parsed_actions(self, tmp_path):
        """Verify integration with _parse_rsync_output()."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        rsync_output = [
            b"cd+++++++++ dir1/\n",
            b">f+++++++++ file1.txt\n",
            b"*deleting oldfile.txt\n",
            b">f..t...... file2.txt\n",
        ]

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout(rsync_output)
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            results = list(fs.rsync_ext(str(src), str(dst)))

            assert len(results) == 4
            assert results[0] == ("dir1/", fs.Actions.CREATE, "")
            assert results[1] == ("file1.txt", fs.Actions.CREATE, "")
            assert results[2] == ("oldfile.txt", fs.Actions.DELETE, "")
            assert results[3] == ("file2.txt", fs.Actions.REWRITE, "")

    def test_calls_process_wait(self, tmp_path):
        """Ensure subprocess.wait() is called to clean up process."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout([b">f+++++++++ test.txt\n"])
            mock_popen.return_value = mock_process

            list(fs.rsync_ext(str(src), str(dst)))

            mock_process.wait.assert_called_once()

    def test_single_line_output(self, tmp_path):
        """Handle case where rsync produces single file output."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout([b">f+++++++++ newfile.txt\n"])
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            results = list(fs.rsync_ext(str(src), str(dst)))

            assert len(results) == 1
            assert results[0][0] == "newfile.txt"
            assert results[0][1] == fs.Actions.CREATE

    def test_multiple_files_in_output(self, tmp_path):
        """Process multiple file operations in single rsync run."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()
        dst.mkdir()

        # realistic rsync output with multiple operations
        rsync_output = [
            b"cd+++++++++ docs/\n",
            b">f+++++++++ docs/readme.md\n",
            b">f+++++++++ config.json\n",
            b".f..t...... existing.txt\n",
            b"*deleting old/\n",
        ]

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = MockStdout(rsync_output)
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            results = list(fs.rsync_ext(str(src), str(dst)))

            assert len(results) == 5
            assert results[0][0] == "docs/"
            assert results[1][0] == "docs/readme.md"
            assert results[2][0] == "config.json"
            assert results[3][0] == "existing.txt"
            assert results[4][0] == "old/"


class TestRsyncHardlinkImmutability:
    """
    Regression tests: rsync() is run against a staging directory that
    was populated by hardlinking in the previous, completed snapshot
    (curateipsum.backup.hardlink_dir). Any in-place metadata change made
    while updating staging must never mutate that previous snapshot's
    files via the shared inode.
    """

    def test_permission_change_does_not_mutate_shared_hardlink(
            self, common_fs_dirs, tmp_path
    ):
        src_dir, dst_dir = common_fs_dirs
        # Independent source file with new content/mtime but the SAME
        # eventual permissions the old snapshot file already has - only
        # the fallback "update permissions and ownership" branch should
        # fire, not a full rewrite (which would already be safe via
        # rm+recreate).
        src_fpath = create_file(str(src_dir))
        os.chmod(src_fpath, 0o600)

        # Simulate staging (dst_dir) having been hardlinked in from the
        # previous, completed snapshot: a separate directory tree outside
        # dst_dir, sharing an inode with the staging file, with content
        # and mtime matching src (so only permissions differ) but the old
        # mode.
        dst_fpath = os.path.join(str(dst_dir),
                                 relpath(src_fpath, str(src_dir), str(dst_dir)))
        prior_snapshot_fpath = str(tmp_path / "prior_snapshot")
        with open(prior_snapshot_fpath, "w") as f:
            f.write(open(src_fpath).read())
        os.chmod(prior_snapshot_fpath, 0o644)
        src_stat = os.lstat(src_fpath)
        os.utime(prior_snapshot_fpath, (src_stat.st_atime, src_stat.st_mtime))
        os.link(prior_snapshot_fpath, dst_fpath)
        prior_mode_before = os.lstat(prior_snapshot_fpath).st_mode
        assert os.lstat(dst_fpath).st_ino == os.lstat(
            prior_snapshot_fpath).st_ino  # sanity: genuinely shared

        all(fs.rsync(str(src_dir), str(dst_dir)))

        assert os.lstat(dst_fpath).st_mode == os.lstat(src_fpath).st_mode
        assert os.lstat(prior_snapshot_fpath).st_mode == prior_mode_before
        # dst must now have its own inode, no longer shared
        assert os.lstat(dst_fpath).st_ino != os.lstat(
            prior_snapshot_fpath).st_ino

    def test_symlink_metadata_never_touches_external_target(
            self, common_fs_dirs, tmp_path
    ):
        src_dir, dst_dir = common_fs_dirs
        external_target = tmp_path / "external_target"
        external_target.mkdir()
        (external_target / "canary").write_text("do-not-touch")
        external_mode_before = os.lstat(str(external_target)).st_mode

        link_name = "a_symlink"
        os.symlink(str(external_target), os.path.join(str(src_dir), link_name))
        os.symlink(str(external_target), os.path.join(str(dst_dir), link_name))

        all(fs.rsync(str(src_dir), str(dst_dir)))

        assert os.lstat(str(external_target)).st_mode == external_mode_before
        assert (external_target / "canary").read_text() == "do-not-touch"
