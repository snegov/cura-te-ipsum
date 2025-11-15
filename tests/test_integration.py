"""
Integration tests for the full backup workflow.
Tests the complete backup process from start to finish.
"""
import os
import tempfile
import time
from unittest import TestCase

from curateipsum import backup as bk


class TestFullBackupWorkflow(TestCase):
    """Integration tests for complete backup workflow."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_integration_")
        self.backups_dir = os.path.join(self.temp_dir.name, "backups")
        self.source_dir = os.path.join(self.temp_dir.name, "source")
        os.makedirs(self.backups_dir)
        os.makedirs(self.source_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initial_backup_creation(self):
        """Test creating the first backup"""
        # Create some files in source
        with open(os.path.join(self.source_dir, "file1.txt"), "w") as f:
            f.write("content1")
        with open(os.path.join(self.source_dir, "file2.txt"), "w") as f:
            f.write("content2")

        # Run backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Verify backup was created
        backups = os.listdir(self.backups_dir)
        # Filter out lock files
        backups = [b for b in backups if not b.startswith(".")]
        self.assertEqual(len(backups), 1)

        # Verify files exist in backup
        backup_path = os.path.join(self.backups_dir, backups[0])
        source_name = os.path.basename(self.source_dir)
        backup_file1 = os.path.join(backup_path, source_name, "file1.txt")
        backup_file2 = os.path.join(backup_path, source_name, "file2.txt")

        self.assertTrue(os.path.exists(backup_file1))
        self.assertTrue(os.path.exists(backup_file2))

        # Verify backup marker exists
        marker_files = [f for f in os.listdir(backup_path) if f.startswith(".backup_finished")]
        self.assertEqual(len(marker_files), 1)

    def test_incremental_backup_with_hardlinks(self):
        """Test that second backup uses hardlinks for unchanged files"""
        # Create initial file
        src_file = os.path.join(self.source_dir, "unchanged.txt")
        with open(src_file, "w") as f:
            f.write("unchanged content")

        # First backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Wait a bit to ensure different timestamp
        time.sleep(1.1)

        # Second backup (no changes)
        # Add a new file to trigger a new backup
        with open(os.path.join(self.source_dir, "new.txt"), "w") as f:
            f.write("new content")

        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Verify two backups exist
        backups = sorted([b for b in os.listdir(self.backups_dir) if not b.startswith(".")])
        self.assertEqual(len(backups), 2)

        # Verify unchanged file is hardlinked
        source_name = os.path.basename(self.source_dir)
        file1_path = os.path.join(self.backups_dir, backups[0], source_name, "unchanged.txt")
        file2_path = os.path.join(self.backups_dir, backups[1], source_name, "unchanged.txt")

        stat1 = os.stat(file1_path)
        stat2 = os.stat(file2_path)

        # Same inode means hardlinked
        self.assertEqual(stat1.st_ino, stat2.st_ino)
        # Link count should be 2
        self.assertEqual(stat1.st_nlink, 2)

    def test_backup_delta_directory(self):
        """Test that delta directory contains changed files"""
        # Create initial file
        with open(os.path.join(self.source_dir, "file.txt"), "w") as f:
            f.write("original")

        # First backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        time.sleep(1.1)

        # Modify file
        with open(os.path.join(self.source_dir, "file.txt"), "w") as f:
            f.write("modified")

        # Second backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Check delta directory in second backup
        backups = sorted([b for b in os.listdir(self.backups_dir) if not b.startswith(".")])
        second_backup = backups[1]
        delta_dir = os.path.join(self.backups_dir, second_backup, bk.DELTA_DIR)

        # Delta directory should exist and contain the modified file
        self.assertTrue(os.path.isdir(delta_dir))

        source_name = os.path.basename(self.source_dir)
        delta_file = os.path.join(delta_dir, source_name, "file.txt")
        self.assertTrue(os.path.exists(delta_file))

    def test_cleanup_retains_recent_backups(self):
        """Test that cleanup doesn't remove recent backups"""
        # Create multiple backups
        for i in range(3):
            with open(os.path.join(self.source_dir, f"file{i}.txt"), "w") as f:
                f.write(f"content {i}")

            bk.initiate_backup(
                sources=[self.source_dir],
                backups_dir=self.backups_dir,
                dry_run=False
            )
            time.sleep(1.1)

        # Run cleanup with keep_all=10 (all should be kept)
        bk.cleanup_old_backups(
            backups_dir=self.backups_dir,
            dry_run=False,
            keep_all=10
        )

        # All backups should still exist
        backups = [b for b in os.listdir(self.backups_dir) if not b.startswith(".")]
        self.assertEqual(len(backups), 3)

    def test_dry_run_creates_no_backup(self):
        """Test that dry run doesn't create actual backup"""
        with open(os.path.join(self.source_dir, "file.txt"), "w") as f:
            f.write("content")

        # Dry run backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=True
        )

        # No backup should be created
        backups = [b for b in os.listdir(self.backups_dir) if not b.startswith(".")]
        self.assertEqual(len(backups), 0)

    def test_no_backup_if_no_changes(self):
        """Test that no backup is created if nothing changed"""
        # Create initial file
        with open(os.path.join(self.source_dir, "file.txt"), "w") as f:
            f.write("content")

        # First backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        time.sleep(1.1)

        # Second backup with no changes
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Only one backup should exist
        backups = [b for b in os.listdir(self.backups_dir) if not b.startswith(".")]
        self.assertEqual(len(backups), 1)

    def test_lock_prevents_concurrent_backups(self):
        """Test that lock file prevents concurrent backup runs"""
        with open(os.path.join(self.source_dir, "file.txt"), "w") as f:
            f.write("content")

        # Manually create lock file
        lock_acquired = bk.set_backups_lock(self.backups_dir)
        self.assertTrue(lock_acquired)

        try:
            # Try to run backup (should be blocked by lock)
            # We can't actually test this without spawning a subprocess,
            # but we can verify the lock exists
            lock_path = os.path.join(self.backups_dir, bk.LOCK_FILE)
            self.assertTrue(os.path.exists(lock_path))
        finally:
            bk.release_backups_lock(self.backups_dir)

        # After releasing lock, backup should work
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        backups = [b for b in os.listdir(self.backups_dir) if not b.startswith(".")]
        self.assertEqual(len(backups), 1)

    def test_multiple_source_directories(self):
        """Test backing up multiple source directories"""
        # Create second source
        source2_dir = os.path.join(self.temp_dir.name, "source2")
        os.makedirs(source2_dir)

        # Create files in both sources
        with open(os.path.join(self.source_dir, "file1.txt"), "w") as f:
            f.write("source1")
        with open(os.path.join(source2_dir, "file2.txt"), "w") as f:
            f.write("source2")

        # Backup both sources
        bk.initiate_backup(
            sources=[self.source_dir, source2_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Verify both sources are in backup
        backups = [b for b in os.listdir(self.backups_dir) if not b.startswith(".")]
        self.assertEqual(len(backups), 1)

        backup_path = os.path.join(self.backups_dir, backups[0])
        source1_name = os.path.basename(self.source_dir)
        source2_name = os.path.basename(source2_dir)

        self.assertTrue(os.path.exists(os.path.join(backup_path, source1_name, "file1.txt")))
        self.assertTrue(os.path.exists(os.path.join(backup_path, source2_name, "file2.txt")))


class TestBackupRecovery(TestCase):
    """Integration tests for backup recovery scenarios."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_recovery_")
        self.backups_dir = os.path.join(self.temp_dir.name, "backups")
        self.source_dir = os.path.join(self.temp_dir.name, "source")
        self.restore_dir = os.path.join(self.temp_dir.name, "restore")
        os.makedirs(self.backups_dir)
        os.makedirs(self.source_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_restore_from_backup(self):
        """Test restoring files from a backup"""
        # Create source files
        src_file = os.path.join(self.source_dir, "important.txt")
        with open(src_file, "w") as f:
            f.write("important data")

        # Create backup
        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Simulate data loss - delete source
        os.unlink(src_file)
        self.assertFalse(os.path.exists(src_file))

        # Restore from backup
        backups = [b for b in os.listdir(self.backups_dir) if not b.startswith(".")]
        backup_path = os.path.join(self.backups_dir, backups[0])
        source_name = os.path.basename(self.source_dir)
        backed_up_file = os.path.join(backup_path, source_name, "important.txt")

        # Verify file exists in backup
        self.assertTrue(os.path.exists(backed_up_file))

        # Restore file
        os.makedirs(self.restore_dir)
        import shutil
        shutil.copy2(backed_up_file, os.path.join(self.restore_dir, "important.txt"))

        # Verify restored content
        with open(os.path.join(self.restore_dir, "important.txt"), "r") as f:
            self.assertEqual(f.read(), "important data")

    def test_find_file_version_in_old_backup(self):
        """Test finding an old version of a file"""
        src_file = os.path.join(self.source_dir, "document.txt")

        # Create version 1
        with open(src_file, "w") as f:
            f.write("version 1")

        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )
        time.sleep(1.1)

        # Create version 2
        with open(src_file, "w") as f:
            f.write("version 2")

        bk.initiate_backup(
            sources=[self.source_dir],
            backups_dir=self.backups_dir,
            dry_run=False
        )

        # Verify we can access both versions
        backups = sorted([b for b in os.listdir(self.backups_dir) if not b.startswith(".")])
        source_name = os.path.basename(self.source_dir)

        # First backup has version 1
        backup1_file = os.path.join(self.backups_dir, backups[0], source_name, "document.txt")
        with open(backup1_file, "r") as f:
            self.assertEqual(f.read(), "version 1")

        # Second backup has version 2
        backup2_file = os.path.join(self.backups_dir, backups[1], source_name, "document.txt")
        with open(backup2_file, "r") as f:
            self.assertEqual(f.read(), "version 2")
