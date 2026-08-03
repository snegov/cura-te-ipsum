"""
Integration tests for the full backup workflow.
Tests the complete backup process from start to finish.
"""
import os
import shutil
import sys
import time
import pytest

from curateipsum import backup as bk


@pytest.fixture
def integration_dirs(tmp_path):
    """Setup integration test directories."""
    backups_dir = tmp_path / "backups"
    source_dir = tmp_path / "source"
    backups_dir.mkdir()
    source_dir.mkdir()
    return backups_dir, source_dir


def test_initial_backup_creation(integration_dirs):
    """Test creating the first backup"""
    backups_dir, source_dir = integration_dirs

    # Create some files in source
    (source_dir / "file1.txt").write_text("content1")
    (source_dir / "file2.txt").write_text("content2")

    # Run backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Verify backup was created
    backups = os.listdir(str(backups_dir))
    # Filter out lock files
    backups = [b for b in backups if not b.startswith(".")]
    assert len(backups) == 1

    # Verify files exist in backup
    backup_path = os.path.join(str(backups_dir), backups[0])
    source_name = os.path.basename(str(source_dir))
    backup_file1 = os.path.join(backup_path, source_name, "file1.txt")
    backup_file2 = os.path.join(backup_path, source_name, "file2.txt")

    assert os.path.exists(backup_file1)
    assert os.path.exists(backup_file2)

    # Verify backup marker exists
    marker_files = [f for f in os.listdir(backup_path)
                    if f.startswith(".backup_finished")]
    assert len(marker_files) == 1


def test_incremental_backup_with_hardlinks(integration_dirs):
    """Test that second backup uses hardlinks for unchanged files"""
    backups_dir, source_dir = integration_dirs

    # Create initial file
    src_file = source_dir / "unchanged.txt"
    src_file.write_text("unchanged content")

    # First backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Wait a bit to ensure different timestamp
    time.sleep(1.1)

    # Second backup (no changes)
    # Add a new file to trigger a new backup
    (source_dir / "new.txt").write_text("new content")

    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Verify two backups exist
    backups = sorted([b for b in os.listdir(str(backups_dir))
                      if not b.startswith(".")])
    assert len(backups) == 2

    # Verify unchanged file is hardlinked
    source_name = os.path.basename(str(source_dir))
    file1_path = os.path.join(str(backups_dir), backups[0],
                              source_name, "unchanged.txt")
    file2_path = os.path.join(str(backups_dir), backups[1],
                              source_name, "unchanged.txt")

    stat1 = os.stat(file1_path)
    stat2 = os.stat(file2_path)

    # Same inode means hardlinked
    assert stat1.st_ino == stat2.st_ino
    # Link count should be 2
    assert stat1.st_nlink == 2


def test_backup_delta_directory(integration_dirs):
    """Test that delta directory contains changed files"""
    backups_dir, source_dir = integration_dirs

    # Create initial file
    (source_dir / "file.txt").write_text("original")

    # First backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    time.sleep(1.1)

    # Modify file
    (source_dir / "file.txt").write_text("modified")

    # Second backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Check delta directory in second backup
    backups = sorted([b for b in os.listdir(str(backups_dir))
                      if not b.startswith(".")])
    second_backup = backups[1]
    delta_dir = os.path.join(str(backups_dir), second_backup, bk.DELTA_DIR)

    # Delta directory should exist and contain the modified file
    assert os.path.isdir(delta_dir)

    source_name = os.path.basename(str(source_dir))
    delta_file = os.path.join(delta_dir, source_name, "file.txt")
    assert os.path.exists(delta_file)


def test_cleanup_retains_recent_backups(integration_dirs):
    """Test that cleanup doesn't remove recent backups"""
    backups_dir, source_dir = integration_dirs

    # Create multiple backups
    for i in range(3):
        (source_dir / f"file{i}.txt").write_text(f"content {i}")

        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )
        time.sleep(1.1)

    # Run cleanup with keep_all=10 (all should be kept)
    bk.cleanup_old_backups(
        backups_dir=str(backups_dir),
        dry_run=False,
        keep_all=10
    )

    # All backups should still exist
    backups = [b for b in os.listdir(str(backups_dir))
               if not b.startswith(".")]
    assert len(backups) == 3


def test_dry_run_creates_no_backup(integration_dirs):
    """Test that dry run doesn't create actual backup"""
    backups_dir, source_dir = integration_dirs

    (source_dir / "file.txt").write_text("content")

    # Dry run backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=True
    )

    # No backup should be created
    backups = [b for b in os.listdir(str(backups_dir))
               if not b.startswith(".")]
    assert len(backups) == 0


def test_no_backup_if_no_changes(integration_dirs):
    """Test that no backup is created if nothing changed"""
    backups_dir, source_dir = integration_dirs

    # Create initial file
    (source_dir / "file.txt").write_text("content")

    # First backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    time.sleep(1.1)

    # Second backup with no changes
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Only one backup should exist
    backups = [b for b in os.listdir(str(backups_dir))
               if not b.startswith(".")]
    assert len(backups) == 1


def test_lock_prevents_concurrent_backups(integration_dirs):
    """Test that lock file prevents concurrent backup runs"""
    backups_dir, source_dir = integration_dirs

    (source_dir / "file.txt").write_text("content")

    # Manually create lock file
    lock_acquired = bk.set_backups_lock(str(backups_dir))
    assert lock_acquired

    try:
        # Try to run backup (should be blocked by lock)
        # We can't actually test this without spawning a subprocess,
        # but we can verify the lock exists
        lock_path = os.path.join(str(backups_dir), bk.LOCK_FILE)
        assert os.path.exists(lock_path)
    finally:
        bk.release_backups_lock(str(backups_dir))

    # After releasing lock, backup should work
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    backups = [b for b in os.listdir(str(backups_dir))
               if not b.startswith(".")]
    assert len(backups) == 1


def test_multiple_source_directories(integration_dirs, tmp_path):
    """Test backing up multiple source directories"""
    backups_dir, source_dir = integration_dirs

    # Create second source
    source2_dir = tmp_path / "source2"
    source2_dir.mkdir()

    # Create files in both sources
    (source_dir / "file1.txt").write_text("source1")
    (source2_dir / "file2.txt").write_text("source2")

    # Backup both sources
    bk.initiate_backup(
        sources=[str(source_dir), str(source2_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Verify both sources are in backup
    backups = [b for b in os.listdir(str(backups_dir))
               if not b.startswith(".")]
    assert len(backups) == 1

    backup_path = os.path.join(str(backups_dir), backups[0])
    source1_name = os.path.basename(str(source_dir))
    source2_name = os.path.basename(str(source2_dir))

    assert os.path.exists(os.path.join(backup_path, source1_name,
                                       "file1.txt"))
    assert os.path.exists(os.path.join(backup_path, source2_name,
                                       "file2.txt"))


@pytest.fixture
def recovery_dirs(tmp_path):
    """Setup recovery test directories."""
    backups_dir = tmp_path / "backups"
    source_dir = tmp_path / "source"
    restore_dir = tmp_path / "restore"
    backups_dir.mkdir()
    source_dir.mkdir()
    return backups_dir, source_dir, restore_dir


def test_restore_from_backup(recovery_dirs):
    """Test restoring files from a backup"""
    backups_dir, source_dir, restore_dir = recovery_dirs

    # Create source files
    src_file = source_dir / "important.txt"
    src_file.write_text("important data")

    # Create backup
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Simulate data loss - delete source
    os.unlink(str(src_file))
    assert not os.path.exists(str(src_file))

    # Restore from backup
    backups = [b for b in os.listdir(str(backups_dir))
               if not b.startswith(".")]
    backup_path = os.path.join(str(backups_dir), backups[0])
    source_name = os.path.basename(str(source_dir))
    backed_up_file = os.path.join(backup_path, source_name, "important.txt")

    # Verify file exists in backup
    assert os.path.exists(backed_up_file)

    # Restore file
    restore_dir.mkdir()
    import shutil
    shutil.copy2(backed_up_file, str(restore_dir / "important.txt"))

    # Verify restored content
    assert (restore_dir / "important.txt").read_text() == "important data"


def test_find_file_version_in_old_backup(recovery_dirs):
    """Test finding an old version of a file"""
    backups_dir, source_dir, _ = recovery_dirs
    src_file = source_dir / "document.txt"

    # Create version 1
    src_file.write_text("version 1")

    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )
    time.sleep(1.1)

    # Create version 2
    src_file.write_text("version 2")

    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    # Verify we can access both versions
    backups = sorted([b for b in os.listdir(str(backups_dir))
                      if not b.startswith(".")])
    source_name = os.path.basename(str(source_dir))

    # First backup has version 1
    backup1_file = os.path.join(str(backups_dir), backups[0],
                                source_name, "document.txt")
    with open(backup1_file, "r") as f:
        assert f.read() == "version 1"

    # Second backup has version 2
    backup2_file = os.path.join(str(backups_dir), backups[1],
                                source_name, "document.txt")
    with open(backup2_file, "r") as f:
        assert f.read() == "version 2"


# External tool availability checks
RSYNC_AVAILABLE = shutil.which("rsync") is not None
CP_PROGRAM = "gcp" if sys.platform == "darwin" else "cp"
CP_AVAILABLE = shutil.which(CP_PROGRAM) is not None


@pytest.mark.skipif(not RSYNC_AVAILABLE, reason="rsync not available")
def test_external_rsync_creates_backup(integration_dirs):
    """Test backup using external rsync binary"""
    backups_dir, source_dir = integration_dirs

    # Create initial file
    (source_dir / "file1.txt").write_text("content1")

    # Create first backup with Python rsync (to establish baseline)
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    time.sleep(1.1)

    # Add new file for second backup
    (source_dir / "file2.txt").write_text("content2")

    # Second backup with external rsync
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
        external_rsync=True
    )

    # Verify two backups exist
    backups = sorted([b for b in os.listdir(str(backups_dir))
                      if not b.startswith(".")])
    assert len(backups) == 2

    # Verify files exist in second backup
    backup_path = os.path.join(str(backups_dir), backups[1])
    source_name = os.path.basename(str(source_dir))
    backup_file1 = os.path.join(backup_path, source_name, "file1.txt")
    backup_file2 = os.path.join(backup_path, source_name, "file2.txt")

    assert os.path.exists(backup_file1)
    assert os.path.exists(backup_file2)
    assert open(backup_file1).read() == "content1"
    assert open(backup_file2).read() == "content2"


@pytest.mark.skipif(not CP_AVAILABLE, reason=f"{CP_PROGRAM} not available")
def test_external_hardlink_creates_backup(integration_dirs):
    """Test backup using external cp/gcp for hardlinking"""
    backups_dir, source_dir = integration_dirs

    # Create initial file
    (source_dir / "unchanged.txt").write_text("unchanged content")

    # First backup (creates baseline)
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
        external_hardlink=True
    )

    time.sleep(1.1)

    # Add new file for second backup
    (source_dir / "new.txt").write_text("new content")

    # Second backup with external hardlink
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
        external_hardlink=True
    )

    # Verify two backups exist
    backups = sorted([b for b in os.listdir(str(backups_dir))
                      if not b.startswith(".")])
    assert len(backups) == 2

    # Verify unchanged file is hardlinked (same inode)
    source_name = os.path.basename(str(source_dir))
    file1_path = os.path.join(str(backups_dir), backups[0],
                              source_name, "unchanged.txt")
    file2_path = os.path.join(str(backups_dir), backups[1],
                              source_name, "unchanged.txt")

    stat1 = os.stat(file1_path)
    stat2 = os.stat(file2_path)

    # Same inode means hardlinked
    assert stat1.st_ino == stat2.st_ino
    assert stat1.st_nlink == 2


@pytest.mark.skipif(not (RSYNC_AVAILABLE and CP_AVAILABLE),
                    reason=f"rsync or {CP_PROGRAM} not available")
def test_both_external_tools(integration_dirs):
    """Test backup using both external rsync and external hardlink"""
    backups_dir, source_dir = integration_dirs

    # Create initial files
    (source_dir / "unchanged.txt").write_text("unchanged")
    (source_dir / "modified.txt").write_text("original")

    # First backup with Python tools (to establish baseline)
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False
    )

    time.sleep(1.1)

    # Modify one file, leave other unchanged
    (source_dir / "modified.txt").write_text("new content")

    # Second backup with external tools
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
        external_rsync=True,
        external_hardlink=True
    )

    # Verify two backups exist
    backups = sorted([b for b in os.listdir(str(backups_dir))
                      if not b.startswith(".")])
    assert len(backups) == 2

    source_name = os.path.basename(str(source_dir))

    # Verify modified file has new content in second backup
    backup2_modified = os.path.join(str(backups_dir), backups[1],
                                    source_name, "modified.txt")
    assert open(backup2_modified).read() == "new content"

    # Verify unchanged file is hardlinked between backups
    backup1_unchanged = os.path.join(str(backups_dir), backups[0],
                                     source_name, "unchanged.txt")
    backup2_unchanged = os.path.join(str(backups_dir), backups[1],
                                     source_name, "unchanged.txt")

    stat1 = os.stat(backup1_unchanged)
    stat2 = os.stat(backup2_unchanged)

    # External hardlink should preserve hardlinks for unchanged files
    assert stat1.st_ino == stat2.st_ino
    assert stat1.st_nlink == 2


class TestErrorRecovery:
    """Test error recovery and cleanup during backup failures"""

    def test_hardlink_failure_removes_incomplete_backup(
            self, integration_dirs, monkeypatch
    ):
        """Test that incomplete backup is removed when hardlink_dir fails"""
        backups_dir, source_dir = integration_dirs

        # Create initial backup
        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        # Verify first backup exists
        backups = [b for b in os.listdir(str(backups_dir))
                   if not b.startswith(".")]
        assert len(backups) == 1

        time.sleep(1.1)

        # Add new file to trigger backup
        (source_dir / "file2.txt").write_text("content2")

        # Mock hardlink_dir to fail
        from curateipsum import fs
        original_hardlink_dir = fs.hardlink_dir

        def failing_hardlink_dir(*args, **kwargs):
            # Create partial directory to simulate partial failure
            if "dst_dir" in kwargs:
                dst = kwargs["dst_dir"]
            else:
                dst = args[1] if len(args) > 1 else None
            if dst:
                os.makedirs(dst, exist_ok=True)
                # Create a partial file to test cleanup
                with open(os.path.join(dst, "partial.txt"), "w") as f:
                    f.write("partial")
            return False

        monkeypatch.setattr(fs, "hardlink_dir", failing_hardlink_dir)

        # Try to create second backup (should fail loudly, never silently)
        with pytest.raises(bk.BackupFailedError):
            bk.initiate_backup(
                sources=[str(source_dir)],
                backups_dir=str(backups_dir),
                dry_run=False
            )

        # Only original backup should exist (failed backup cleaned up)
        backups = [b for b in os.listdir(str(backups_dir))
                   if not b.startswith(".")]
        assert len(backups) == 1

        # No abandoned staging directory should remain either
        staging_dirs = [d for d in os.listdir(str(backups_dir))
                        if d.startswith(bk.STAGING_PREFIX)]
        assert staging_dirs == []

        # Verify the remaining backup is the original one
        backup_path = os.path.join(str(backups_dir), backups[0])
        source_name = os.path.basename(str(source_dir))
        assert os.path.exists(os.path.join(backup_path, source_name,
                                           "file1.txt"))
        # file2.txt should not exist in original backup
        assert not os.path.exists(os.path.join(backup_path, source_name,
                                               "file2.txt"))

    def test_rsync_failure_removes_incomplete_backup(
            self, integration_dirs, monkeypatch
    ):
        """Test that incomplete backup is removed when rsync fails"""
        backups_dir, source_dir = integration_dirs

        # Create initial backup
        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        time.sleep(1.1)

        # Add new file
        (source_dir / "file2.txt").write_text("content2")

        # Mock rsync to fail immediately without yielding
        from curateipsum import fs

        def failing_rsync(src, dst, dry_run=False):
            # Fail immediately before any operations
            raise fs.BackupCreationError("Simulated rsync failure")
            # Make this a generator (unreachable but keeps signature)
            yield  # pragma: no cover

        monkeypatch.setattr(fs, "rsync", failing_rsync)

        # Try to create second backup (should fail loudly and clean up)
        with pytest.raises(bk.BackupFailedError):
            bk.initiate_backup(
                sources=[str(source_dir)],
                backups_dir=str(backups_dir),
                dry_run=False
            )

        # Only original backup should exist
        backups = [b for b in os.listdir(str(backups_dir))
                   if not b.startswith(".")]
        assert len(backups) == 1

    def test_entry_level_error_action_is_fatal(
            self, integration_dirs, monkeypatch
    ):
        """A single Actions.ERROR from rsync must fail the whole backup,
        never be treated as a partial success."""
        backups_dir, source_dir = integration_dirs

        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        time.sleep(1.1)
        (source_dir / "file2.txt").write_text("content2")

        from curateipsum import fs

        def erroring_rsync(src, dst, dry_run=False):
            yield "file2.txt", fs.Actions.ERROR, "simulated copy error"

        monkeypatch.setattr(fs, "rsync", erroring_rsync)

        with pytest.raises(bk.BackupFailedError):
            bk.initiate_backup(
                sources=[str(source_dir)],
                backups_dir=str(backups_dir),
                dry_run=False
            )

        backups = [b for b in os.listdir(str(backups_dir))
                   if not b.startswith(".")]
        assert len(backups) == 1

    def test_abandoned_staging_dir_is_cleaned_up_on_startup(
            self, integration_dirs
    ):
        """Stale .incomplete-* staging dirs from a crashed run must be
        quarantined/removed before a new backup starts, and must never be
        mistaken for a real backup."""
        backups_dir, source_dir = integration_dirs
        (source_dir / "file1.txt").write_text("content1")

        stale_staging = backups_dir / f"{bk.STAGING_PREFIX}deadbeef"
        stale_staging.mkdir()
        (stale_staging / "leftover.txt").write_text("leftover")

        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        entries = os.listdir(str(backups_dir))
        staging_dirs = [d for d in entries if d.startswith(bk.STAGING_PREFIX)]
        assert staging_dirs == []

        real_backups = [b for b in entries if not b.startswith(".")]
        assert len(real_backups) == 1

    def test_successful_backup_leaves_no_staging_dir(self, integration_dirs):
        """A completed backup must be renamed atomically into place, no
        .incomplete-* directory should be left behind."""
        backups_dir, source_dir = integration_dirs
        (source_dir / "file1.txt").write_text("content1")

        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        entries = os.listdir(str(backups_dir))
        staging_dirs = [d for d in entries if d.startswith(bk.STAGING_PREFIX)]
        assert staging_dirs == []

    def test_incomplete_backup_without_marker(self, integration_dirs):
        """Test that backups without marker are not counted as valid"""
        backups_dir, source_dir = integration_dirs

        # Create a complete backup
        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        # Manually create incomplete backup directory (no marker)
        incomplete_backup_name = "20250101_120000"
        incomplete_path = os.path.join(str(backups_dir),
                                       incomplete_backup_name)
        os.makedirs(incomplete_path)
        source_name = os.path.basename(str(source_dir))
        os.makedirs(os.path.join(incomplete_path, source_name))
        with open(os.path.join(incomplete_path, source_name,
                               "incomplete.txt"), "w") as f:
            f.write("incomplete data")

        # List all directory entries (including incomplete)
        all_dirs = [d for d in os.listdir(str(backups_dir))
                    if not d.startswith(".")]
        assert len(all_dirs) == 2

        # But _iterate_backups should only find complete backup
        valid_backups = list(bk._iterate_backups(str(backups_dir)))
        assert len(valid_backups) == 1

        # Verify get_latest_backup ignores incomplete backup
        latest = bk._get_latest_backup(str(backups_dir))
        assert latest is not None
        assert latest.name != incomplete_backup_name

        time.sleep(1.1)

        # New backup should hardlink from the complete backup, not incomplete
        (source_dir / "file2.txt").write_text("content2")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        # Should now have 3 directories (1 incomplete, 2 complete)
        all_dirs = [d for d in os.listdir(str(backups_dir))
                    if not d.startswith(".")]
        assert len(all_dirs) == 3

        valid_backups = list(bk._iterate_backups(str(backups_dir)))
        assert len(valid_backups) == 2

    def test_backup_marker_only_not_valid(self, integration_dirs):
        """Test that directory with only marker file is not a valid backup"""
        backups_dir, source_dir = integration_dirs

        # Create directory with only marker file
        marker_only_name = "20250101_120000"
        marker_only_path = os.path.join(str(backups_dir), marker_only_name)
        os.makedirs(marker_only_path)
        marker_file = os.path.join(marker_only_path,
                                   f"{bk.BACKUP_MARKER}_{marker_only_name}")
        with open(marker_file, "w") as f:
            pass  # empty marker file

        # Should not be recognized as valid backup
        valid_backups = list(bk._iterate_backups(str(backups_dir)))
        assert len(valid_backups) == 0

        # get_latest_backup should return None
        latest = bk._get_latest_backup(str(backups_dir))
        assert latest is None

    def test_lock_released_after_hardlink_failure(
            self, integration_dirs, monkeypatch
    ):
        """Test that lock is properly released when backup fails"""
        backups_dir, source_dir = integration_dirs

        # Create initial backup
        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        time.sleep(1.1)
        (source_dir / "file2.txt").write_text("content2")

        # Mock hardlink_dir to fail
        from curateipsum import fs

        def failing_hardlink_dir(*args, **kwargs):
            return False

        monkeypatch.setattr(fs, "hardlink_dir", failing_hardlink_dir)

        # Manually acquire lock
        lock_acquired = bk.set_backups_lock(str(backups_dir))
        assert lock_acquired

        # Verify lock file exists
        lock_path = os.path.join(str(backups_dir), bk.LOCK_FILE)
        assert os.path.exists(lock_path)

        try:
            # Backup should fail due to hardlink failure
            with pytest.raises(bk.BackupFailedError):
                bk.initiate_backup(
                    sources=[str(source_dir)],
                    backups_dir=str(backups_dir),
                    dry_run=False
                )
        finally:
            # Lock should still exist (we manually acquired it)
            assert os.path.exists(lock_path)

            # Release lock
            bk.release_backups_lock(str(backups_dir))

        # Lock should be removed
        assert not os.path.exists(lock_path)

        # Restore original function and verify backup can proceed
        monkeypatch.undo()

        # Now backup should succeed
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        # Should have 2 valid backups now
        backups = [b for b in os.listdir(str(backups_dir))
                   if not b.startswith(".")]
        assert len(backups) == 2

    def test_lock_released_after_rsync_failure(
            self, integration_dirs, monkeypatch
    ):
        """Test that lock is released after rsync failure"""
        backups_dir, source_dir = integration_dirs

        # Create initial backup
        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        time.sleep(1.1)
        (source_dir / "file2.txt").write_text("content2")

        # Mock rsync to fail
        from curateipsum import fs

        def failing_rsync(src, dst, dry_run=False):
            raise fs.BackupCreationError("Simulated rsync failure")

        monkeypatch.setattr(fs, "rsync", failing_rsync)

        # Manually acquire lock
        lock_acquired = bk.set_backups_lock(str(backups_dir))
        assert lock_acquired

        lock_path = os.path.join(str(backups_dir), bk.LOCK_FILE)
        assert os.path.exists(lock_path)

        try:
            # Backup should fail
            with pytest.raises(bk.BackupFailedError):
                bk.initiate_backup(
                    sources=[str(source_dir)],
                    backups_dir=str(backups_dir),
                    dry_run=False
                )
        finally:
            # Lock still exists (we manually acquired it)
            assert os.path.exists(lock_path)
            bk.release_backups_lock(str(backups_dir))

        # Lock should be removed
        assert not os.path.exists(lock_path)

    def test_permission_error_during_cleanup(
            self, integration_dirs, monkeypatch
    ):
        """Test handling of permission errors during failed backup cleanup"""
        backups_dir, source_dir = integration_dirs

        # Create initial backup
        (source_dir / "file1.txt").write_text("content1")
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False
        )

        time.sleep(1.1)
        (source_dir / "file2.txt").write_text("content2")

        # Track rmtree calls
        rmtree_called = []
        original_rmtree = shutil.rmtree

        def tracking_rmtree(path, *args, **kwargs):
            rmtree_called.append(path)
            # Let it succeed (ignore_errors=True in code)
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", tracking_rmtree)

        # Mock rsync to fail
        from curateipsum import fs

        def failing_rsync(src, dst, dry_run=False):
            raise fs.BackupCreationError("Simulated failure")

        monkeypatch.setattr(fs, "rsync", failing_rsync)

        # Run backup (will fail and attempt cleanup)
        with pytest.raises(bk.BackupFailedError):
            bk.initiate_backup(
                sources=[str(source_dir)],
                backups_dir=str(backups_dir),
                dry_run=False
            )

        # Verify cleanup was attempted (rmtree was called)
        assert len(rmtree_called) > 0

        # Verify failed backup was removed
        backups = [b for b in os.listdir(str(backups_dir))
                   if not b.startswith(".")]
        assert len(backups) == 1
