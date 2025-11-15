"""
Extended tests for filesystem operations in fs.py module.
Tests critical functionality like copy_file, rsync, and hardlink operations.
"""
import os
import tempfile
from unittest import TestCase

from curateipsum import fs


class TestCopyFile(TestCase):
    """Test suite for copy_file function."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_copy_")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_copy_simple_file(self):
        """Test copying a simple file"""
        src_path = os.path.join(self.temp_dir.name, "source.txt")
        dst_path = os.path.join(self.temp_dir.name, "dest.txt")

        # Create source file
        content = b"Hello, World!" * 1000
        with open(src_path, "wb") as f:
            f.write(content)

        # Copy file
        fs.copy_file(src_path, dst_path)

        # Verify destination exists and has same content
        self.assertTrue(os.path.exists(dst_path))
        with open(dst_path, "rb") as f:
            self.assertEqual(f.read(), content)

    def test_copy_large_file(self):
        """Test copying a large file (> buffer size)"""
        src_path = os.path.join(self.temp_dir.name, "large.bin")
        dst_path = os.path.join(self.temp_dir.name, "large_copy.bin")

        # Create file larger than buffer (128KB)
        content = b"x" * (200 * 1024)  # 200KB
        with open(src_path, "wb") as f:
            f.write(content)

        # Copy file
        fs.copy_file(src_path, dst_path)

        # Verify
        self.assertTrue(os.path.exists(dst_path))
        self.assertEqual(os.path.getsize(dst_path), len(content))

    def test_copy_preserves_permissions(self):
        """Test that copy_file preserves file permissions"""
        src_path = os.path.join(self.temp_dir.name, "executable.sh")
        dst_path = os.path.join(self.temp_dir.name, "executable_copy.sh")

        # Create source file with specific permissions
        with open(src_path, "w") as f:
            f.write("#!/bin/bash\necho test")
        os.chmod(src_path, 0o755)

        # Copy file
        fs.copy_file(src_path, dst_path)

        # Verify permissions
        src_stat = os.stat(src_path)
        dst_stat = os.stat(dst_path)
        self.assertEqual(src_stat.st_mode, dst_stat.st_mode)


class TestCopyDirEntry(TestCase):
    """Test suite for copy_direntry function."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_copydir_")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_copy_file_entry(self):
        """Test copying a file DirEntry"""
        src_path = os.path.join(self.temp_dir.name, "source.txt")
        dst_path = os.path.join(self.temp_dir.name, "dest.txt")

        # Create source file
        with open(src_path, "w") as f:
            f.write("test content")
        os.chmod(src_path, 0o644)

        # Create DirEntry and copy
        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        # Verify
        self.assertTrue(os.path.isfile(dst_path))
        with open(dst_path, "r") as f:
            self.assertEqual(f.read(), "test content")

    def test_copy_directory_entry(self):
        """Test copying a directory DirEntry"""
        src_path = os.path.join(self.temp_dir.name, "srcdir")
        dst_path = os.path.join(self.temp_dir.name, "dstdir")

        # Create source directory
        os.mkdir(src_path)
        os.chmod(src_path, 0o755)

        # Create DirEntry and copy
        entry = fs.PseudoDirEntry(src_path)
        fs.copy_direntry(entry, dst_path)

        # Verify
        self.assertTrue(os.path.isdir(dst_path))

    def test_copy_symlink_entry(self):
        """Test copying a symlink DirEntry using real os.DirEntry"""
        target_path = os.path.join(self.temp_dir.name, "target.txt")
        src_link = os.path.join(self.temp_dir.name, "source_link")
        dst_link = os.path.join(self.temp_dir.name, "dest_link")

        # Create target and symlink
        with open(target_path, "w") as f:
            f.write("target")
        os.symlink(target_path, src_link)

        # Use os.DirEntry from scandir for proper symlink detection
        # PseudoDirEntry doesn't properly detect symlinks
        with os.scandir(self.temp_dir.name) as it:
            for entry in it:
                if entry.name == "source_link":
                    fs.copy_direntry(entry, dst_link)
                    break

        # Verify symlink was copied
        self.assertTrue(os.path.islink(dst_link))
        self.assertEqual(os.readlink(dst_link), target_path)


class TestRsync(TestCase):
    """Test suite for rsync function."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_rsync_")
        self.src_dir = os.path.join(self.temp_dir.name, "source")
        self.dst_dir = os.path.join(self.temp_dir.name, "dest")
        os.mkdir(self.src_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rsync_creates_destination(self):
        """Test that rsync creates destination directory if missing"""
        # Destination doesn't exist yet
        self.assertFalse(os.path.exists(self.dst_dir))

        # Run rsync
        list(fs.rsync(self.src_dir, self.dst_dir))

        # Destination should now exist
        self.assertTrue(os.path.isdir(self.dst_dir))

    def test_rsync_copies_new_files(self):
        """Test that rsync copies new files"""
        os.mkdir(self.dst_dir)

        # Create files in source
        with open(os.path.join(self.src_dir, "file1.txt"), "w") as f:
            f.write("content1")
        with open(os.path.join(self.src_dir, "file2.txt"), "w") as f:
            f.write("content2")

        # Run rsync
        actions = list(fs.rsync(self.src_dir, self.dst_dir))

        # Verify files were created
        self.assertTrue(os.path.exists(os.path.join(self.dst_dir, "file1.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.dst_dir, "file2.txt")))

        # Check that CREATE actions were reported
        create_actions = [a for a in actions if a[1] == fs.Actions.CREATE]
        self.assertEqual(len(create_actions), 2)

    def test_rsync_deletes_missing_files(self):
        """Test that rsync deletes files not in source"""
        os.mkdir(self.dst_dir)

        # Create file only in destination
        dst_file = os.path.join(self.dst_dir, "old_file.txt")
        with open(dst_file, "w") as f:
            f.write("old content")

        # Run rsync
        actions = list(fs.rsync(self.src_dir, self.dst_dir))

        # Verify file was deleted
        self.assertFalse(os.path.exists(dst_file))

        # Check that DELETE action was reported
        delete_actions = [a for a in actions if a[1] == fs.Actions.DELETE]
        self.assertEqual(len(delete_actions), 1)

    def test_rsync_updates_modified_files(self):
        """Test that rsync updates modified files"""
        os.mkdir(self.dst_dir)

        # Create file in both locations
        src_file = os.path.join(self.src_dir, "file.txt")
        dst_file = os.path.join(self.dst_dir, "file.txt")

        with open(src_file, "w") as f:
            f.write("original")
        with open(dst_file, "w") as f:
            f.write("modified")

        # Make source newer
        import time
        time.sleep(0.1)
        with open(src_file, "w") as f:
            f.write("updated content")

        # Run rsync
        actions = list(fs.rsync(self.src_dir, self.dst_dir))

        # Verify file was updated
        with open(dst_file, "r") as f:
            self.assertEqual(f.read(), "updated content")

        # Check that REWRITE action was reported
        rewrite_actions = [a for a in actions if a[1] == fs.Actions.REWRITE]
        self.assertGreater(len(rewrite_actions), 0)

    def test_rsync_preserves_permissions(self):
        """Test that rsync preserves file permissions"""
        os.mkdir(self.dst_dir)

        # Create executable file in source
        src_file = os.path.join(self.src_dir, "script.sh")
        with open(src_file, "w") as f:
            f.write("#!/bin/bash\n")
        os.chmod(src_file, 0o755)

        # Run rsync
        list(fs.rsync(self.src_dir, self.dst_dir))

        # Verify permissions were preserved
        dst_file = os.path.join(self.dst_dir, "script.sh")
        dst_stat = os.stat(dst_file)
        src_stat = os.stat(src_file)
        self.assertEqual(dst_stat.st_mode, src_stat.st_mode)


class TestHardlinkDir(TestCase):
    """Test suite for hardlink_dir function."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_hardlink_")
        self.src_dir = os.path.join(self.temp_dir.name, "source")
        self.dst_dir = os.path.join(self.temp_dir.name, "dest")
        os.mkdir(self.src_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_hardlink_creates_destination(self):
        """Test that hardlink_dir creates destination directory"""
        result = fs.hardlink_dir(self.src_dir, self.dst_dir)

        self.assertTrue(result)
        self.assertTrue(os.path.isdir(self.dst_dir))

    def test_hardlink_links_files(self):
        """Test that files are hardlinked, not copied"""
        # Create file in source
        src_file = os.path.join(self.src_dir, "file.txt")
        with open(src_file, "w") as f:
            f.write("test content")

        # Hardlink directory
        fs.hardlink_dir(self.src_dir, self.dst_dir)

        # Verify file exists in destination
        dst_file = os.path.join(self.dst_dir, "file.txt")
        self.assertTrue(os.path.exists(dst_file))

        # Verify they're the same inode (hardlinked)
        src_stat = os.stat(src_file)
        dst_stat = os.stat(dst_file)
        self.assertEqual(src_stat.st_ino, dst_stat.st_ino)

    def test_hardlink_nested_directories(self):
        """Test hardlinking nested directory structure"""
        # Create nested structure
        subdir = os.path.join(self.src_dir, "subdir")
        os.mkdir(subdir)
        with open(os.path.join(subdir, "nested.txt"), "w") as f:
            f.write("nested content")

        # Hardlink directory
        fs.hardlink_dir(self.src_dir, self.dst_dir)

        # Verify nested structure exists
        dst_nested = os.path.join(self.dst_dir, "subdir", "nested.txt")
        self.assertTrue(os.path.exists(dst_nested))

        # Verify hardlink
        src_nested = os.path.join(subdir, "nested.txt")
        src_stat = os.stat(src_nested)
        dst_stat = os.stat(dst_nested)
        self.assertEqual(src_stat.st_ino, dst_stat.st_ino)


class TestScantree(TestCase):
    """Test suite for scantree function."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_scantree_")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scantree_empty_directory(self):
        """Test scanning empty directory"""
        entries = list(fs.scantree(self.temp_dir.name))
        self.assertEqual(len(entries), 0)

    def test_scantree_flat_directory(self):
        """Test scanning flat directory structure"""
        # Create some files
        for i in range(3):
            with open(os.path.join(self.temp_dir.name, f"file{i}.txt"), "w") as f:
                f.write(f"content {i}")

        entries = list(fs.scantree(self.temp_dir.name))
        self.assertEqual(len(entries), 3)

    def test_scantree_nested_directories(self):
        """Test scanning nested directory structure"""
        # Create nested structure
        subdir1 = os.path.join(self.temp_dir.name, "dir1")
        subdir2 = os.path.join(subdir1, "dir2")
        os.makedirs(subdir2)

        with open(os.path.join(self.temp_dir.name, "root.txt"), "w") as f:
            f.write("root")
        with open(os.path.join(subdir1, "sub1.txt"), "w") as f:
            f.write("sub1")
        with open(os.path.join(subdir2, "sub2.txt"), "w") as f:
            f.write("sub2")

        # Scan with dir_first=True
        entries = list(fs.scantree(self.temp_dir.name, dir_first=True))

        # Should find: root.txt, dir1, sub1.txt, dir2, sub2.txt
        self.assertEqual(len(entries), 5)

        # Verify directories come before their contents
        names = [os.path.basename(e.path) for e in entries]
        dir1_idx = names.index("dir1")
        sub1_idx = names.index("sub1.txt")
        self.assertLess(dir1_idx, sub1_idx)


class TestRmDirentry(TestCase):
    """Test suite for rm_direntry function."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_rm_")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_remove_file(self):
        """Test removing a file"""
        file_path = os.path.join(self.temp_dir.name, "test.txt")
        with open(file_path, "w") as f:
            f.write("test")

        entry = fs.PseudoDirEntry(file_path)
        fs.rm_direntry(entry)

        self.assertFalse(os.path.exists(file_path))

    def test_remove_empty_directory(self):
        """Test removing an empty directory"""
        dir_path = os.path.join(self.temp_dir.name, "testdir")
        os.mkdir(dir_path)

        entry = fs.PseudoDirEntry(dir_path)
        fs.rm_direntry(entry)

        self.assertFalse(os.path.exists(dir_path))

    def test_remove_directory_with_contents(self):
        """Test removing a directory with files"""
        dir_path = os.path.join(self.temp_dir.name, "testdir")
        os.mkdir(dir_path)
        with open(os.path.join(dir_path, "file.txt"), "w") as f:
            f.write("test")

        entry = fs.PseudoDirEntry(dir_path)
        fs.rm_direntry(entry)

        self.assertFalse(os.path.exists(dir_path))

    def test_remove_symlink(self):
        """Test removing a symlink using real os.DirEntry"""
        target = os.path.join(self.temp_dir.name, "target.txt")
        link = os.path.join(self.temp_dir.name, "link")

        with open(target, "w") as f:
            f.write("target")
        os.symlink(target, link)

        # Use os.DirEntry from scandir for proper symlink detection
        # PseudoDirEntry doesn't properly detect symlinks
        with os.scandir(self.temp_dir.name) as it:
            for entry in it:
                if entry.name == "link":
                    fs.rm_direntry(entry)
                    break

        # Link should be removed, target should remain
        self.assertFalse(os.path.exists(link))
        self.assertFalse(os.path.islink(link))
        self.assertTrue(os.path.exists(target))
