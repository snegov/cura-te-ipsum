"""Tests for PseudoDirEntry class."""
import os

from curateipsum import fs


class TestPseudoDirEntry:
    """Test PseudoDirEntry class behavior, especially follow_symlinks handling."""

    def test_regular_file_is_file(self, tmp_path):
        """Regular file should report as file, not dir or symlink."""
        filepath = tmp_path / "file.txt"
        filepath.write_text("test")
        
        entry = fs.PseudoDirEntry(str(filepath))
        
        assert entry.is_file(follow_symlinks=True)
        assert entry.is_file(follow_symlinks=False)
        assert not entry.is_dir(follow_symlinks=True)
        assert not entry.is_dir(follow_symlinks=False)
        assert not entry.is_symlink()

    def test_regular_dir_is_dir(self, tmp_path):
        """Regular directory should report as dir, not file or symlink."""
        dirpath = tmp_path / "testdir"
        dirpath.mkdir()
        
        entry = fs.PseudoDirEntry(str(dirpath))
        
        assert entry.is_dir(follow_symlinks=True)
        assert entry.is_dir(follow_symlinks=False)
        assert not entry.is_file(follow_symlinks=True)
        assert not entry.is_file(follow_symlinks=False)
        assert not entry.is_symlink()

    def test_symlink_to_file_follow_true(self, tmp_path):
        """Symlink to file with follow_symlinks=True should report as file."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        assert entry.is_file(follow_symlinks=True)
        assert entry.is_symlink()

    def test_symlink_to_file_follow_false(self, tmp_path):
        """Symlink to file with follow_symlinks=False should not report as file."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        assert not entry.is_file(follow_symlinks=False)
        assert not entry.is_dir(follow_symlinks=False)
        assert entry.is_symlink()

    def test_symlink_to_dir_follow_true(self, tmp_path):
        """Symlink to dir with follow_symlinks=True should report as dir."""
        dirpath = tmp_path / "testdir"
        linkpath = tmp_path / "linkdir"
        dirpath.mkdir()
        linkpath.symlink_to(dirpath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        assert entry.is_dir(follow_symlinks=True)
        assert entry.is_symlink()

    def test_symlink_to_dir_follow_false(self, tmp_path):
        """Symlink to dir with follow_symlinks=False should not report as dir."""
        dirpath = tmp_path / "testdir"
        linkpath = tmp_path / "linkdir"
        dirpath.mkdir()
        linkpath.symlink_to(dirpath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        assert not entry.is_dir(follow_symlinks=False)
        assert not entry.is_file(follow_symlinks=False)
        assert entry.is_symlink()

    def test_matches_real_direntry_file(self, tmp_path):
        """PseudoDirEntry should match real DirEntry for regular file."""
        filepath = tmp_path / "file.txt"
        filepath.write_text("test")
        
        pseudo = fs.PseudoDirEntry(str(filepath))
        real = next(os.scandir(tmp_path))
        
        assert pseudo.is_file(follow_symlinks=True) == real.is_file(follow_symlinks=True)
        assert pseudo.is_file(follow_symlinks=False) == real.is_file(follow_symlinks=False)
        assert pseudo.is_dir(follow_symlinks=True) == real.is_dir(follow_symlinks=True)
        assert pseudo.is_dir(follow_symlinks=False) == real.is_dir(follow_symlinks=False)
        assert pseudo.is_symlink() == real.is_symlink()

    def test_matches_real_direntry_symlink(self, tmp_path):
        """PseudoDirEntry should match real DirEntry for symlink."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test")
        linkpath.symlink_to(filepath)
        
        pseudo = fs.PseudoDirEntry(str(linkpath))
        real = [e for e in os.scandir(tmp_path) if e.name == "link.txt"][0]
        
        assert pseudo.is_file(follow_symlinks=True) == real.is_file(follow_symlinks=True)
        assert pseudo.is_file(follow_symlinks=False) == real.is_file(follow_symlinks=False)
        assert pseudo.is_dir(follow_symlinks=True) == real.is_dir(follow_symlinks=True)
        assert pseudo.is_dir(follow_symlinks=False) == real.is_dir(follow_symlinks=False)
        assert pseudo.is_symlink() == real.is_symlink()

    def test_stat_follow_symlinks_true(self, tmp_path):
        """stat(follow_symlinks=True) should return target's stat."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test content")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        stat_result = entry.stat(follow_symlinks=True)
        
        # should return file's size, not symlink size
        assert stat_result.st_size == 12

    def test_stat_follow_symlinks_false(self, tmp_path):
        """stat(follow_symlinks=False) should return symlink's stat."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test content")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        stat_result = entry.stat(follow_symlinks=False)
        
        # should return symlink size, not file size
        assert stat_result.st_size != 12

    def test_stat_caching_separate(self, tmp_path):
        """stat() should cache follow_symlinks=True/False separately."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test content")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        stat_follow = entry.stat(follow_symlinks=True)
        stat_nofollow = entry.stat(follow_symlinks=False)
        
        # should return different results
        assert stat_follow.st_size == 12
        assert stat_nofollow.st_size != 12
        
        # call again to verify caching works
        assert entry.stat(follow_symlinks=True).st_size == 12
        assert entry.stat(follow_symlinks=False).st_size != 12

    def test_name_and_path_attributes(self, tmp_path):
        """Test that name and path attributes are set correctly."""
        filepath = tmp_path / "file.txt"
        filepath.write_text("test")
        
        entry = fs.PseudoDirEntry(str(filepath))
        
        assert entry.name == "file.txt"
        assert entry.path == str(filepath)

    def test_str_representation(self, tmp_path):
        """__str__ should return name."""
        filepath = tmp_path / "file.txt"
        filepath.write_text("test")
        
        entry = fs.PseudoDirEntry(str(filepath))
        
        assert str(entry) == "file.txt"

    def test_abspath_not_realpath(self, tmp_path):
        """Constructor should use abspath, not realpath (preserves symlinks)."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        # path should point to symlink, not resolved target
        assert entry.path == str(linkpath)
        assert entry.name == "link.txt"
        assert entry.is_symlink()

    def test_caching_is_dir(self, tmp_path):
        """is_dir() should cache result for follow_symlinks=True."""
        dirpath = tmp_path / "testdir"
        dirpath.mkdir()
        
        entry = fs.PseudoDirEntry(str(dirpath))
        
        # first call caches
        assert entry.is_dir(follow_symlinks=True)
        assert entry._is_dir is True
        
        # second call uses cache
        assert entry.is_dir(follow_symlinks=True)

    def test_caching_is_file(self, tmp_path):
        """is_file() should cache result for follow_symlinks=True."""
        filepath = tmp_path / "file.txt"
        filepath.write_text("test")
        
        entry = fs.PseudoDirEntry(str(filepath))
        
        # first call caches
        assert entry.is_file(follow_symlinks=True)
        assert entry._is_file is True
        
        # second call uses cache
        assert entry.is_file(follow_symlinks=True)

    def test_caching_is_symlink(self, tmp_path):
        """is_symlink() should cache result."""
        filepath = tmp_path / "file.txt"
        linkpath = tmp_path / "link.txt"
        filepath.write_text("test")
        linkpath.symlink_to(filepath)
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        # first call caches
        assert entry.is_symlink()
        assert entry._is_symlink is True
        
        # second call uses cache
        assert entry.is_symlink()

    def test_broken_symlink_is_symlink(self, tmp_path):
        """Broken symlink should still be detected as symlink."""
        linkpath = tmp_path / "broken_link"
        linkpath.symlink_to("/nonexistent/path")
        
        entry = fs.PseudoDirEntry(str(linkpath))
        
        assert entry.is_symlink()
        assert not entry.is_file(follow_symlinks=False)
        assert not entry.is_dir(follow_symlinks=False)

    def test_relative_path_converted_to_absolute(self, tmp_path):
        """Relative paths should be converted to absolute."""
        filepath = tmp_path / "file.txt"
        filepath.write_text("test")
        
        # change to tmp_path and use relative path
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            entry = fs.PseudoDirEntry("file.txt")
            
            assert os.path.isabs(entry.path)
            assert entry.name == "file.txt"
        finally:
            os.chdir(original_cwd)

    def test_nonexistent_path_attributes(self, tmp_path):
        """PseudoDirEntry should work for paths that don't exist yet."""
        filepath = tmp_path / "future_file.txt"
        
        # path doesn't exist yet
        assert not filepath.exists()
        
        entry = fs.PseudoDirEntry(str(filepath))
        
        # should still have name and path attributes
        assert entry.name == "future_file.txt"
        assert entry.path == str(filepath)
