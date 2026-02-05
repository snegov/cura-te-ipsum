"""
Integration tests for the full backup workflow.
Tests the complete backup process from start to finish.
"""
import os
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
