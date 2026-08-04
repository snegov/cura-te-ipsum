"""Tests for the restore module (restore.py)."""
import os

import pytest

from curateipsum import backup as bk
from curateipsum import restore


@pytest.fixture
def restore_dirs(tmp_path):
    backups_dir = tmp_path / "backups"
    source_dir = tmp_path / "source"
    dest_dir = tmp_path / "dest"
    backups_dir.mkdir()
    source_dir.mkdir()
    return backups_dir, source_dir, dest_dir


def _make_snapshot(backups_dir, source_dir):
    entry = bk.initiate_backup(
        sources=[str(source_dir)], backups_dir=str(backups_dir))
    assert entry is not None
    return bk.find_backup(str(backups_dir))


class TestRestoreSnapshot:
    def test_restores_files_and_dirs(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "subdir").mkdir()
        (source_dir / "file1.txt").write_text("content1")
        (source_dir / "subdir" / "file2.txt").write_text("content2")

        snapshot = _make_snapshot(backups_dir, source_dir)
        skipped = restore.restore_snapshot(snapshot, str(dest_dir))

        assert skipped == []
        src_name = os.path.basename(str(source_dir))
        restored_root = dest_dir / src_name
        assert (restored_root / "file1.txt").read_text() == "content1"
        assert (restored_root / "subdir" / "file2.txt").read_text() == (
            "content2")

    def test_preserves_symlinks(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "real.txt").write_text("data")
        os.symlink("real.txt", str(source_dir / "link.txt"))

        snapshot = _make_snapshot(backups_dir, source_dir)
        restore.restore_snapshot(snapshot, str(dest_dir))

        src_name = os.path.basename(str(source_dir))
        link_path = dest_dir / src_name / "link.txt"
        assert os.path.islink(str(link_path))
        assert os.readlink(str(link_path)) == "real.txt"

    def test_excludes_snapshot_bookkeeping(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")

        snapshot = _make_snapshot(backups_dir, source_dir)
        restore.restore_snapshot(snapshot, str(dest_dir))

        restored_names = os.listdir(str(dest_dir))
        assert bk.DELTA_DIR not in restored_names
        assert not any(n.startswith(bk.BACKUP_MARKER)
                       for n in restored_names)

    def test_overwrite_never_skips_existing(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("new-content")

        snapshot = _make_snapshot(backups_dir, source_dir)
        src_name = os.path.basename(str(source_dir))
        existing = dest_dir / src_name / "file1.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("old-content")

        skipped = restore.restore_snapshot(
            snapshot, str(dest_dir), overwrite=restore.OVERWRITE_NEVER)

        assert os.path.join(src_name, "file1.txt") in skipped
        assert existing.read_text() == "old-content"

    def test_overwrite_always_replaces_existing(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("new-content")

        snapshot = _make_snapshot(backups_dir, source_dir)
        src_name = os.path.basename(str(source_dir))
        existing = dest_dir / src_name / "file1.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("old-content")

        skipped = restore.restore_snapshot(
            snapshot, str(dest_dir), overwrite=restore.OVERWRITE_ALWAYS)

        assert skipped == []
        assert existing.read_text() == "new-content"

    def test_dry_run_writes_nothing(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")
        dest_dir.mkdir()

        snapshot = _make_snapshot(backups_dir, source_dir)
        skipped = restore.restore_snapshot(
            snapshot, str(dest_dir), dry_run=True)

        assert skipped == []
        assert os.listdir(str(dest_dir)) == []

    def test_rel_paths_restricts_restore(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "keep.txt").write_text("keep")
        (source_dir / "skip.txt").write_text("skip")

        snapshot = _make_snapshot(backups_dir, source_dir)
        src_name = os.path.basename(str(source_dir))
        restore.restore_snapshot(
            snapshot, str(dest_dir),
            rel_paths=[os.path.join(src_name, "keep.txt")])

        restored_root = dest_dir / src_name
        assert (restored_root / "keep.txt").read_text() == "keep"
        assert not (restored_root / "skip.txt").exists()

    def test_refuses_to_restore_into_snapshot_itself(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")

        snapshot = _make_snapshot(backups_dir, source_dir)
        with pytest.raises(restore.RestoreError):
            restore.restore_snapshot(snapshot, snapshot.path)

    def test_unknown_overwrite_policy_rejected(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")

        snapshot = _make_snapshot(backups_dir, source_dir)
        with pytest.raises(ValueError):
            restore.restore_snapshot(
                snapshot, str(dest_dir), overwrite="sometimes")


class TestVerifyRestored:
    def test_verify_matches_after_clean_restore(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")

        snapshot = _make_snapshot(backups_dir, source_dir)
        restore.restore_snapshot(snapshot, str(dest_dir))

        mismatches = restore.verify_restored(snapshot, str(dest_dir))
        assert mismatches == []

    def test_verify_detects_corrupted_restore(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")

        snapshot = _make_snapshot(backups_dir, source_dir)
        restore.restore_snapshot(snapshot, str(dest_dir))

        src_name = os.path.basename(str(source_dir))
        (dest_dir / src_name / "file1.txt").write_text("corrupted")

        mismatches = restore.verify_restored(snapshot, str(dest_dir))
        assert mismatches == [os.path.join(src_name, "file1.txt")]

    def test_verify_detects_missing_restore(self, restore_dirs):
        backups_dir, source_dir, dest_dir = restore_dirs
        (source_dir / "file1.txt").write_text("content1")

        snapshot = _make_snapshot(backups_dir, source_dir)
        dest_dir.mkdir()

        mismatches = restore.verify_restored(snapshot, str(dest_dir))
        assert mismatches == [
            os.path.join(os.path.basename(str(source_dir)), "file1.txt")
        ]


class TestFindBackup:
    def test_finds_latest_by_default(self, restore_dirs):
        backups_dir, source_dir, _ = restore_dirs
        (source_dir / "file1.txt").write_text("v1")
        first = _make_snapshot(backups_dir, source_dir)

        (source_dir / "file1.txt").write_text("v2")
        bk.initiate_backup(sources=[str(source_dir)],
                           backups_dir=str(backups_dir))

        latest = bk.find_backup(str(backups_dir))
        assert latest.name != first.name

    def test_finds_by_explicit_name(self, restore_dirs):
        backups_dir, source_dir, _ = restore_dirs
        (source_dir / "file1.txt").write_text("v1")
        first = _make_snapshot(backups_dir, source_dir)

        found = bk.find_backup(str(backups_dir), first.name)
        assert found.name == first.name

    def test_raises_on_unknown_name(self, restore_dirs):
        backups_dir, source_dir, _ = restore_dirs
        (source_dir / "file1.txt").write_text("v1")
        _make_snapshot(backups_dir, source_dir)

        with pytest.raises(bk.BackupFailedError):
            bk.find_backup(str(backups_dir), "20000101_000000")

    def test_raises_when_no_backups_exist(self, restore_dirs):
        backups_dir, _, _ = restore_dirs
        with pytest.raises(bk.BackupFailedError):
            bk.find_backup(str(backups_dir))
