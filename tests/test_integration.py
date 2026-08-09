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


def test_dry_run_leaves_backups_dir_byte_for_byte_unchanged(integration_dirs):
    """
    A dry-run must never create a staging directory, hardlink, lock
    metadata, or any other trace on disk - not even a dotfile. Compare
    every entry's full stat() (not just name/existence) before and
    after, so an in-place mutation of an existing entry (e.g. the
    previous snapshot getting chmod'd) can't slip past a listing-only
    check.
    """
    backups_dir, source_dir = integration_dirs

    (source_dir / "file.txt").write_text("original")
    bk.initiate_backup(
        sources=[str(source_dir)], backups_dir=str(backups_dir),
        dry_run=False
    )

    def _snapshot_all_stats(root):
        result = {}
        for dirpath, dirnames, filenames in os.walk(root):
            for name in dirnames + filenames:
                path = os.path.join(dirpath, name)
                st = os.lstat(path)
                result[path] = (st.st_mode, st.st_mtime_ns, st.st_ino,
                                st.st_size)
        return result

    before = _snapshot_all_stats(str(backups_dir))

    # Change the source so the dry-run has something to report
    # (create, rewrite, and permission-change candidates all included).
    (source_dir / "file.txt").write_text("changed")
    (source_dir / "new.txt").write_text("new")

    bk.initiate_backup(
        sources=[str(source_dir)], backups_dir=str(backups_dir),
        dry_run=True
    )
    bk.cleanup_old_backups(backups_dir=str(backups_dir), dry_run=True)

    after = _snapshot_all_stats(str(backups_dir))
    assert before == after


def test_dry_run_cleanup_does_not_create_repo_id_file(integration_dirs):
    """
    cleanup_old_backups(dry_run=True) must not create the repo-id file
    as a side effect of computing what it would delete - that file's
    on-disk creation is itself a mutation a dry-run must never make.
    """
    backups_dir, source_dir = integration_dirs

    (source_dir / "file.txt").write_text("content")
    bk.initiate_backup(
        sources=[str(source_dir)], backups_dir=str(backups_dir),
        dry_run=False
    )

    # A real backup already creates the repo-id file (the manifest needs
    # it); remove it to simulate a legacy repo predating that file, so a
    # dry-run cleanup recreating it would actually be observable.
    repo_id_path = os.path.join(str(backups_dir), bk.REPO_ID_FILE)
    assert os.path.exists(repo_id_path)
    os.remove(repo_id_path)

    bk.cleanup_old_backups(backups_dir=str(backups_dir), dry_run=True,
                           keep_all=0)

    assert not os.path.exists(repo_id_path)


def test_dry_run_reports_changes_against_previous_snapshot(integration_dirs):
    """
    A dry-run's reported operations must reflect a real diff against the
    latest snapshot, not just "everything is new" - proving the new
    direct-comparison path (no throwaway staging copy) actually diffs
    against the right target.
    """
    backups_dir, source_dir = integration_dirs

    (source_dir / "unchanged.txt").write_text("same")
    (source_dir / "will_change.txt").write_text("before")
    bk.initiate_backup(
        sources=[str(source_dir)], backups_dir=str(backups_dir),
        dry_run=False
    )

    (source_dir / "will_change.txt").write_text("after")
    (source_dir / "brand_new.txt").write_text("new")

    seen = []
    latest_backup = bk._get_latest_backup(str(backups_dir))
    bk._plan_backup([str(source_dir)], str(backups_dir), latest_backup,
                    fs_rsync_recording(seen))

    # fs_rsync_recording() wraps fs.rsync() directly, so recorded paths
    # are relative to the source root itself (the source-name prefix
    # _plan_backup() adds for logging isn't part of what rsync() yields).
    kinds = {(relpath, action) for relpath, action in seen}
    assert ("will_change.txt", "REWRITE") in kinds
    assert ("brand_new.txt", "CREATE") in kinds
    assert not any(relpath == "unchanged.txt" for relpath, _ in seen)


def fs_rsync_recording(seen):
    """
    Wrap the real fs.rsync() so a test can inspect exactly which
    (relpath, action) pairs a dry-run would report, without depending
    on log output.
    """
    from curateipsum import fs

    def _wrapped(src, dst, dry_run=False):
        for relpath, action, msg in fs.rsync(src, dst, dry_run=dry_run):
            seen.append((relpath, action.name))
            yield relpath, action, msg

    return _wrapped


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

        # Lock should be free again (re-acquirable), even though the lock
        # file itself is intentionally left in place
        assert bk.set_backups_lock(str(backups_dir))
        bk.release_backups_lock(str(backups_dir))

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

        # Lock should be free again (re-acquirable), even though the lock
        # file itself is intentionally left in place
        assert bk.set_backups_lock(str(backups_dir))
        bk.release_backups_lock(str(backups_dir))

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


def test_completed_snapshot_passes_manifest_verification(integration_dirs):
    """A completed snapshot's checksums must verify against its content."""
    backups_dir, source_dir = integration_dirs
    (source_dir / "file1.txt").write_text("content1")
    (source_dir / "file2.txt").write_text("content2")

    snapshot = bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
    )

    assert bk.verify_snapshot(snapshot) == []


def test_verify_snapshot_detects_corruption(integration_dirs):
    """Corrupting a file after backup must be caught by verify_snapshot."""
    backups_dir, source_dir = integration_dirs
    (source_dir / "file1.txt").write_text("content1")

    snapshot = bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
    )

    source_name = os.path.basename(str(source_dir))
    backed_up_file = os.path.join(
        snapshot.path, source_name, "file1.txt"
    )
    with open(backed_up_file, "w") as f:
        f.write("corrupted")

    mismatches = bk.verify_snapshot(snapshot)
    assert os.path.join(source_name, "file1.txt") in mismatches


def test_source_changed_during_copy_fails_backup(integration_dirs,
                                                   monkeypatch):
    """
    A source file that changes size while being copied must fail the
    whole backup rather than produce an inconsistent snapshot.
    """
    backups_dir, source_dir = integration_dirs
    src_file = source_dir / "changing.txt"
    src_file.write_text("x" * 1000)

    real_read = os.read
    call_count = {"n": 0}

    def read_then_truncate(fd, n):
        call_count["n"] += 1
        data = real_read(fd, n)
        if call_count["n"] == 1:
            os.truncate(str(src_file), 10)
        return data

    monkeypatch.setattr(os, "read", read_then_truncate)

    with pytest.raises(bk.BackupFailedError):
        bk.initiate_backup(
            sources=[str(source_dir)],
            backups_dir=str(backups_dir),
            dry_run=False,
        )

    # no completed snapshot must exist after the failure
    backups = [b for b in os.listdir(str(backups_dir))
              if not b.startswith(".")]
    assert backups == []


@pytest.mark.skipif(not RSYNC_AVAILABLE, reason="rsync not available")
def test_external_rsync_snapshot_still_gets_checksums(integration_dirs):
    """
    fs.rsync_ext() (external rsync) never yields a digest in msg, unlike
    fs.rsync() - initiate_backup() must hash the copied files itself in
    that case, or verify_snapshot() silently becomes a no-op whenever
    --external-rsync is used.
    """
    backups_dir, source_dir = integration_dirs
    (source_dir / "file1.txt").write_text("content1")

    # Establish baseline with Python rsync first, same as
    # test_external_rsync_creates_backup: a from-scratch external-rsync
    # run emits a "created directory ..." header line this codebase's
    # itemize-output parser doesn't handle, which is an unrelated,
    # pre-existing limitation.
    bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
    )
    time.sleep(1.1)
    (source_dir / "file2.txt").write_text("content2")

    snapshot = bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
        external_rsync=True,
    )

    manifest = bk._read_manifest(bk._get_backup_marker(snapshot).path)
    assert manifest["checksums"]
    assert bk.verify_snapshot(snapshot) == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"),
                    reason="os.mkfifo not available on this platform")
def test_fifo_excluded_and_recorded_without_blocking(integration_dirs):
    """
    A FIFO in the source must not block the backup (no writer is ever
    attached), must not abort it, and must be recorded in the manifest
    as an exclusion rather than silently disappearing.
    """
    backups_dir, source_dir = integration_dirs
    (source_dir / "file1.txt").write_text("content1")
    os.mkfifo(str(source_dir / "a_fifo"))

    snapshot = bk.initiate_backup(
        sources=[str(source_dir)],
        backups_dir=str(backups_dir),
        dry_run=False,
    )

    assert snapshot is not None
    source_name = os.path.basename(str(source_dir))
    manifest = bk._read_manifest(bk._get_backup_marker(snapshot).path)
    assert manifest["excluded"] == {
        os.path.join(source_name, "a_fifo"): "fifo"
    }
    assert not os.path.lexists(
        os.path.join(snapshot.path, source_name, "a_fifo")
    )
    assert os.path.exists(
        os.path.join(snapshot.path, source_name, "file1.txt")
    )
