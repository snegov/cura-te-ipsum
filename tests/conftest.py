"""Shared pytest fixtures for cura-te-ipsum tests."""
import os
import random
import string
import tempfile
import pytest

from curateipsum import backup as bk, fs


@pytest.fixture
def backup_dir(tmp_path):
    """Provide a temporary backup directory."""
    return tmp_path / "backups"


@pytest.fixture
def source_dir(tmp_path):
    """Provide a temporary source directory."""
    src = tmp_path / "source"
    src.mkdir()
    return src


@pytest.fixture
def add_backup(backup_dir):
    """Factory fixture for creating test backups."""
    backup_dir.mkdir(parents=True, exist_ok=True)

    def _add_backup(backup_name: str) -> fs.PseudoDirEntry:
        backup = fs.PseudoDirEntry(os.path.join(str(backup_dir), backup_name))
        os.mkdir(backup.path)
        bk.set_backup_marker(backup)

        fd, path = tempfile.mkstemp(prefix="backup_file_", dir=backup.path)
        with open(fd, "w") as f:
            f.write(''.join(random.choices(string.printable, k=128)))
        return backup

    return _add_backup


@pytest.fixture
def check_backup_not_empty():
    """Helper to verify backup is not empty."""
    def _check(backup: fs.PseudoDirEntry) -> bool:
        return bool(os.listdir(backup.path))
    return _check


@pytest.fixture
def check_backups(backup_dir, check_backup_not_empty):
    """Helper to verify expected backups exist."""
    def _check(expected_backups):
        backups_list = os.listdir(str(backup_dir))
        assert sorted(b.name for b in expected_backups) == sorted(backups_list)
        for b in expected_backups:
            assert check_backup_not_empty(b)
    return _check


@pytest.fixture
def run_cleanup(backup_dir):
    """Helper to run cleanup_old_backups with default parameters."""
    def _run(**kwargs):
        cleanup_kwargs = {
            "backups_dir": str(backup_dir),
            "dry_run": False,
            "keep_all": None,
            "keep_daily": None,
            "keep_weekly": None,
            "keep_monthly": None,
            "keep_yearly": None,
        }
        cleanup_kwargs.update(**kwargs)
        bk.cleanup_old_backups(**cleanup_kwargs)
    return _run
