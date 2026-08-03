"""Tests for CLI module (cli.py)."""

import sys
from unittest import mock

import pytest

from curateipsum import cli


class TestArgumentParsing:
    """Test command-line argument parsing."""

    def test_requires_backups_dir(self):
        """Should fail when -b flag is missing."""
        with pytest.raises(SystemExit):
            with mock.patch('sys.argv', ['cura-te-ipsum', '/src1']):
                with mock.patch('argparse.ArgumentParser.parse_args') as m:
                    m.side_effect = SystemExit(2)
                    cli.main()

    def test_requires_at_least_one_source(self):
        """Should fail when no sources are provided."""
        with pytest.raises(SystemExit):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b', '/backups']):
                with mock.patch('argparse.ArgumentParser.parse_args') as m:
                    m.side_effect = SystemExit(2)
                    cli.main()

    def test_parses_single_source(self, tmp_path):
        """Should parse single source directory."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups'):
                    with mock.patch('curateipsum.backup.initiate_backup'):
                        with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                            result = cli.main()

        assert result == 0

    def test_parses_multiple_sources(self, tmp_path):
        """Should parse multiple source directories."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        src1 = tmp_path / "src1"
        src1.mkdir()
        src2 = tmp_path / "src2"
        src2.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(src1), str(src2)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups'):
                    with mock.patch('curateipsum.backup.initiate_backup') \
                            as m_init:
                        with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                            result = cli.main()

        assert result == 0
        m_init.assert_called_once()
        call_args = m_init.call_args
        assert call_args.kwargs['sources'] == [str(src1), str(src2)]

    def test_verbose_flag_sets_debug_logging(self, tmp_path):
        """Should enable DEBUG logging when --verbose is set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source),
                                      '--verbose']):
            with mock.patch('logging.basicConfig') as m_logging:
                with mock.patch('curateipsum.backup.set_backups_lock',
                                return_value=True):
                    with mock.patch('curateipsum.backup.cleanup_old_backups'):
                        with mock.patch('curateipsum.backup.initiate_backup'):
                            with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                                cli.main()

        import logging
        m_logging.assert_called_once()
        assert m_logging.call_args.kwargs['level'] == logging.DEBUG

    def test_dry_run_flag_passed_to_backup(self, tmp_path):
        """Should pass dry_run=True when --dry-run is set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source),
                                      '--dry-run']):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups') \
                        as m_cleanup:
                    with mock.patch('curateipsum.backup.initiate_backup') \
                            as m_init:
                        with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                            cli.main()

        assert m_cleanup.call_args.kwargs['dry_run'] is True
        assert m_init.call_args.kwargs['dry_run'] is True

    def test_force_flag_passed_to_lock(self, tmp_path):
        """Should pass force=True to set_backups_lock when --force is set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source),
                                      '--force']):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True) as m_lock:
                with mock.patch('curateipsum.backup.cleanup_old_backups'):
                    with mock.patch('curateipsum.backup.initiate_backup'):
                        with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                            cli.main()

        m_lock.assert_called_once_with(str(backups_dir), True)

    def test_external_rsync_flag_passed_to_backup(self, tmp_path):
        """Should pass external_rsync=True when --external-rsync is set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source),
                                      '--external-rsync']):
            with mock.patch('shutil.which', return_value='/usr/bin/rsync'):
                with mock.patch('curateipsum.backup.set_backups_lock',
                                return_value=True):
                    with mock.patch('curateipsum.backup.cleanup_old_backups'):
                        with mock.patch('curateipsum.backup.initiate_backup') \
                                as m_init:
                            with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                                cli.main()

        assert m_init.call_args.kwargs['external_rsync'] is True

    def test_external_hardlink_flag_passed_to_backup(self, tmp_path):
        """Should pass external_hardlink=True when --external-hardlink is
        set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source),
                                      '--external-hardlink']):
            with mock.patch('shutil.which', return_value='/usr/bin/cp'):
                with mock.patch('curateipsum.backup.set_backups_lock',
                                return_value=True):
                    with mock.patch('curateipsum.backup.cleanup_old_backups'):
                        with mock.patch('curateipsum.backup.initiate_backup') \
                                as m_init:
                            with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                                cli.main()

        assert m_init.call_args.kwargs['external_hardlink'] is True


class TestPlatformValidation:
    """Test platform-specific checks."""

    def test_allows_linux_platform(self, tmp_path):
        """Should allow execution on Linux."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'linux'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source)]):
                with mock.patch('curateipsum.backup.set_backups_lock',
                                return_value=True):
                    with mock.patch('curateipsum.backup.cleanup_old_backups'):
                        with mock.patch('curateipsum.backup.initiate_backup'):
                            with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                                result = cli.main()

        assert result == 0

    def test_allows_darwin_platform(self, tmp_path):
        """Should allow execution on macOS (darwin)."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'darwin'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source)]):
                with mock.patch('curateipsum.backup.set_backups_lock',
                                return_value=True):
                    with mock.patch('curateipsum.backup.cleanup_old_backups'):
                        with mock.patch('curateipsum.backup.initiate_backup'):
                            with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                                result = cli.main()

        assert result == 0

    def test_rejects_windows_platform(self, tmp_path):
        """Should reject Windows platform."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'win32'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source)]):
                result = cli.main()

        assert result == 1

    def test_rejects_unsupported_platform(self, tmp_path):
        """Should reject unsupported platforms."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'freebsd'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source)]):
                result = cli.main()

        assert result == 1


class TestExternalToolValidation:
    """Test validation of external tool availability."""

    def test_requires_rsync_when_external_rsync_enabled(self, tmp_path):
        """Should fail when rsync is missing and --external-rsync is set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source),
                                      '--external-rsync']):
            with mock.patch('shutil.which', return_value=None):
                result = cli.main()

        assert result == 1

    def test_requires_cp_on_linux_when_external_hardlink_enabled(
            self, tmp_path):
        """Should fail when cp is missing on Linux and --external-hardlink is
        set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'linux'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source),
                                          '--external-hardlink']):
                with mock.patch('shutil.which', return_value=None):
                    result = cli.main()

        assert result == 1

    def test_requires_gcp_on_darwin_when_external_hardlink_enabled(
            self, tmp_path):
        """Should fail when gcp is missing on macOS and --external-hardlink is
        set."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'darwin'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source),
                                          '--external-hardlink']):
                with mock.patch('shutil.which', return_value=None):
                    result = cli.main()

        assert result == 1

    def test_checks_correct_tool_on_darwin(self, tmp_path):
        """Should check for gcp (not cp) on macOS."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.platform', 'darwin'):
            with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                          str(backups_dir), str(source),
                                          '--external-hardlink']):
                with mock.patch('shutil.which',
                                side_effect=lambda x: '/usr/bin/gcp'
                                if x == 'gcp' else None):
                    with mock.patch('curateipsum.backup.set_backups_lock',
                                    return_value=True):
                        with mock.patch(
                                'curateipsum.backup.cleanup_old_backups'):
                            with mock.patch(
                                    'curateipsum.backup.initiate_backup'):
                                with mock.patch(
                                    'curateipsum.backup.release_backups_lock'):
                                    result = cli.main()

        assert result == 0


class TestDirectoryValidation:
    """Test validation of backup and source directories."""

    def test_fails_when_backups_dir_missing(self, tmp_path):
        """Should fail when backup directory doesn't exist."""
        backups_dir = tmp_path / "nonexistent"
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            result = cli.main()

        assert result == 1

    def test_fails_when_source_dir_missing(self, tmp_path):
        """Should fail when source directory doesn't exist."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "nonexistent"

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            result = cli.main()

        assert result == 1

    def test_fails_when_any_source_dir_missing(self, tmp_path):
        """Should fail when any source directory doesn't exist."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        src1 = tmp_path / "src1"
        src1.mkdir()
        src2 = tmp_path / "nonexistent"

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(src1), str(src2)]):
            result = cli.main()

        assert result == 1

    def test_converts_backups_dir_to_absolute_path(self, tmp_path):
        """Should convert relative backup directory path to absolute."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b', 'backups',
                                      str(source)]):
            with mock.patch('os.path.abspath',
                            return_value=str(backups_dir)) as m_abspath:
                with mock.patch('os.path.isdir', return_value=True):
                    with mock.patch('curateipsum.backup.set_backups_lock',
                                    return_value=True) as m_lock:
                        with mock.patch(
                                'curateipsum.backup.cleanup_old_backups'):
                            with mock.patch(
                                    'curateipsum.backup.initiate_backup'):
                                with mock.patch(
                                    'curateipsum.backup.release_backups_lock'):
                                    cli.main()

        m_abspath.assert_called_with('backups')
        m_lock.assert_called_once_with(str(backups_dir), False)


class TestLockHandling:
    """Test backup lock acquisition and release."""

    def test_exits_when_lock_acquisition_fails(self, tmp_path):
        """Should exit with code 1 when lock cannot be acquired."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=False):
                result = cli.main()

        assert result == 1

    def test_releases_lock_after_successful_backup(self, tmp_path):
        """Should release lock after backup completes."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups'):
                    with mock.patch('curateipsum.backup.initiate_backup'):
                        with mock.patch(
                            'curateipsum.backup.release_backups_lock') \
                                as m_release:
                            cli.main()

        m_release.assert_called_once_with(str(backups_dir))

    def test_releases_lock_and_exits_nonzero_after_failed_backup(
            self, tmp_path):
        """Should still release lock and return nonzero exit code when
        initiate_backup raises BackupFailedError."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        from curateipsum import backup

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups'):
                    with mock.patch(
                            'curateipsum.backup.initiate_backup',
                            side_effect=backup.BackupFailedError("boom")):
                        with mock.patch(
                            'curateipsum.backup.release_backups_lock') \
                                as m_release:
                            result = cli.main()

        assert result == 1
        m_release.assert_called_once_with(str(backups_dir))


class TestBackupExecution:
    """Test backup execution flow."""

    def test_calls_cleanup_before_initiate(self, tmp_path):
        """Should call cleanup_old_backups before initiate_backup."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        call_order = []

        def mock_cleanup(**kwargs):
            call_order.append('cleanup')

        def mock_initiate(**kwargs):
            call_order.append('initiate')

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups',
                                side_effect=mock_cleanup):
                    with mock.patch('curateipsum.backup.initiate_backup',
                                    side_effect=mock_initiate):
                        with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                            cli.main()

        assert call_order == ['cleanup', 'initiate']

    def test_passes_correct_arguments_to_initiate_backup(self, tmp_path):
        """Should pass all required arguments to initiate_backup."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        src1 = tmp_path / "src1"
        src1.mkdir()
        src2 = tmp_path / "src2"
        src2.mkdir()

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(src1), str(src2),
                                      '--dry-run', '--external-rsync',
                                      '--external-hardlink']):
            with mock.patch('shutil.which', return_value='/usr/bin/tool'):
                with mock.patch('curateipsum.backup.set_backups_lock',
                                return_value=True):
                    with mock.patch('curateipsum.backup.cleanup_old_backups'):
                        with mock.patch('curateipsum.backup.initiate_backup') \
                                as m_init:
                            with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                                cli.main()

        m_init.assert_called_once_with(
            sources=[str(src1), str(src2)],
            backups_dir=str(backups_dir),
            dry_run=True,
            external_rsync=True,
            external_hardlink=True,
        )

    def test_logs_completion_time(self, tmp_path, caplog):
        """Should log time spent after backup completes."""
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()
        source = tmp_path / "src"
        source.mkdir()

        import logging
        caplog.set_level(logging.INFO)

        with mock.patch('sys.argv', ['cura-te-ipsum', '-b',
                                      str(backups_dir), str(source)]):
            with mock.patch('curateipsum.backup.set_backups_lock',
                            return_value=True):
                with mock.patch('curateipsum.backup.cleanup_old_backups'):
                    with mock.patch('curateipsum.backup.initiate_backup'):
                        with mock.patch(
                                'curateipsum.backup.release_backups_lock'):
                            cli.main()

        # check that completion message was logged
        assert any("Finished" in record.message for record in caplog.records)
        assert any("time spent" in record.message
                   for record in caplog.records)
