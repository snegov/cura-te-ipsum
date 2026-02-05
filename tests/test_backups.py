import os
import signal
import pytest
from unittest import mock
from datetime import datetime

from curateipsum import backup as bk


class TestBackupCleanup:
    """Tests for backup cleanup and retention policies."""

    def test_no_backups(self, backup_dir, run_cleanup):
        """Test behaviour with no available backups"""
        backup_dir.mkdir()
        bk.cleanup_old_backups(str(backup_dir))
        assert not os.listdir(str(backup_dir))

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_only_one_backup(self, mock_datetime, add_backup, run_cleanup,
                             check_backups):
        """Test the only backup will not be removed in any case"""
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        # very old backup
        only_backup = add_backup("20010101_0000")
        run_cleanup(keep_all=1)
        check_backups([only_backup])

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_at_least_one_should_be_left(self, mock_datetime, add_backup,
                                          run_cleanup, check_backups):
        """Test at least one backup should be left"""
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            add_backup("20211103_0300"),  # latest, should be kept
            add_backup("20201216_0100"),  # rest should be removed
            add_backup("20200716_0100"),
            add_backup("20181116_0100"),
        ]
        expected_backups = [backups[0]]
        run_cleanup()
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_all_threshold_only(self, mock_datetime, add_backup,
                                      run_cleanup, check_backups):
        """Test threshold for keeping all backups"""
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            add_backup("20211019_0300"),  # keep
            add_backup("20211017_0100"),  # keep
            add_backup("20211016_2300"),  # remove, older than 3 days
        ]
        expected_backups = backups[:2]
        run_cleanup(keep_all=3)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_daily_threshold_only(self, mock_datetime, add_backup,
                                        run_cleanup, check_backups):
        """Test threshold for keeping daily backups"""
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            add_backup("20211019_0300"),  # keep, first daily at 2021-10-19
            add_backup("20211017_2100"),  # remove, not first daily
            add_backup("20211017_0100"),  # remove, not first daily
            add_backup("20211017_0030"),  # keep, first daily at 2021-10-17
            add_backup("20211016_2300"),  # remove, older than 3 days
            add_backup("20211016_0100"),  # remove, older than 3 days
        ]
        expected_backups = [backups[0], backups[3]]
        run_cleanup(keep_daily=3)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_all_and_daily_thresholds(self, mock_datetime, add_backup,
                                            run_cleanup, check_backups):
        """Test threshold for keeping all and daily backups"""
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            add_backup("20211019_0300"),  # keep, newer than 3 days
            add_backup("20211017_0200"),  # keep, newer than 3 days
            add_backup("20211017_0100"),  # keep, newer than 3 days
            add_backup("20211016_2300"),  # remove, not first daily
            add_backup("20211016_2200"),  # keep, first daily at 2021-10-16
            add_backup("20211015_2200"),  # remove, not first daily
            add_backup("20211015_1500"),  # remove, not first daily
            add_backup("20211015_0200"),  # keep, first daily at 2021-10-15
            add_backup("20211014_2200"),  # remove, older than 5 days
            add_backup("20211014_2000"),  # remove, older than 5 days
            add_backup("20211014_1232"),  # remove, older than 5 days
        ]
        expected_backups = backups[0:3] + [backups[4]] + [backups[7]]
        run_cleanup(keep_all=3, keep_daily=5)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_weekly_threshold_only(self, mock_datetime, add_backup,
                                         run_cleanup, check_backups):
        """Test threshold for keeping weekly backups"""
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            add_backup("20211111_0300"),  # remove, not first weekly (Thu)
            add_backup("20211110_0300"),  # remove, not first weekly (Wed)
            add_backup("20211108_0100"),  # keep, first weekly 2021-11-08 (Mon)
            add_backup("20211107_2300"),  # remove, not first weekly (Sun)
            add_backup("20211107_0100"),  # keep, first weekly 2021-11-07 (Sun)
            add_backup("20211031_0100"),  # remove, not first weekly (Sun)
            add_backup("20211025_0100"),  # keep, first weekly 2021-10-25 (Mon)
            add_backup("20211024_0100"),  # remove, not first weekly (Sun)
            add_backup("20211023_0100"),  # remove, not first weekly (Sat)
            add_backup("20211022_0100"),  # keep, first weekly 2021-10-22 (Fri)
            add_backup("20211008_0100"),  # remove, not first weekly (Fri)
            add_backup("20211007_0100"),  # remove, not first weekly (Thu)
            add_backup("20211004_0100"),  # keep, first weekly 2021-10-04 (Mon)
            add_backup("20211003_0100"),  # remove, older than 5 weeks
            add_backup("20211002_0100"),  # remove, older than 5 weeks

        ]
        expected_backups = [backups[2], backups[4], backups[6],
                            backups[9], backups[12]]
        run_cleanup(keep_weekly=5)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_weekly_threshold_inclusive(self, mock_datetime, add_backup,
                                              run_cleanup, check_backups):
        """Test threshold for keeping weekly backups"""
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            add_backup("20211111_0300"),  # remove, not first weekly (Thu)
            add_backup("20211110_0300"),  # keep, first weekly (Wed)
            add_backup("20211107_0100"),  # remove, not first weekly (Sun)
            add_backup("20211102_0100"),  # keep, first weekly (Tue)
        ]
        expected_backups = [backups[1], backups[3]]
        run_cleanup(keep_weekly=5)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_monthly_threshold_only(self, mock_datetime, add_backup,
                                          run_cleanup, check_backups):
        """Test threshold for keeping monthly backups"""
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            add_backup("20211103_0300"),  # keep, first monthly at 2021-11
            add_backup("20211019_0300"),  # remove, not first monthly
            add_backup("20211017_2100"),  # remove, not first monthly
            add_backup("20211017_0100"),  # keep, first monthly at 2021-10
            add_backup("20210916_2300"),  # remove, not first monthly
            add_backup("20210916_0100"),  # keep, first monthly at 2021-09
            add_backup("20210816_0100"),  # remove, not first monthly
            add_backup("20210810_0000"),  # keep, first monthly at 2021-08
            add_backup("20210716_0100"),  # remove, older than 3 months
            add_backup("20210715_0100"),  # remove, older than 3 months
        ]
        expected_backups = [backups[0], backups[3], backups[5], backups[7]]
        run_cleanup(keep_monthly=3)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_yearly_threshold_only(self, mock_datetime, add_backup,
                                         run_cleanup, check_backups):
        """Test threshold for keeping yearly backups"""
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            add_backup("20211103_0300"),  # remove, not first yearly in 2021
            add_backup("20210810_0000"),  # remove, not first yearly in 2021
            add_backup("20210716_0100"),  # keep, first yearly in 2021
            add_backup("20201216_0100"),  # remove, not first yearly in 2020
            add_backup("20200716_0100"),  # keep, first yearly in 2020
            add_backup("20191216_0100"),  # remove, not first yearly in 2019
            add_backup("20190316_0100"),  # keep, first yearly in 2019
            add_backup("20181216_0100"),  # remove, not first yearly in 2018
            add_backup("20181116_0100"),  # keep, first yearly in 2018
            add_backup("20171116_0100"),  # remove, older than 3 years
            add_backup("20171115_0100"),  # remove, older than 3 years
        ]
        expected_backups = [backups[2], backups[4], backups[6], backups[8]]
        run_cleanup(keep_yearly=3)
        check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_dry_run(self, mock_datetime, add_backup, run_cleanup,
                     check_backups):
        """Test dry run does not remove anything"""
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            add_backup("20211103_0300"),
            add_backup("20210810_0000"),
            add_backup("20210716_0100"),
            add_backup("20200716_0100"),
            add_backup("20181116_0100"),
        ]
        run_cleanup(keep_all=2, dry_run=True)
        check_backups(backups)

    @pytest.mark.xfail(reason="Bug #32: coarser retention tiers override finer "
                              "tiers, violating retention guarantees", strict=True)
    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_combined_retention_policies(self, mock_datetime, add_backup,
                                          run_cleanup, check_backups):
        """Test all retention policies working together

        Tests EXPECTED behavior where retention policies honor their
        documented guarantees. Currently fails due to bug where coarser
        retention tiers (weekly/monthly/yearly) can override finer tiers
        (all/daily/weekly/monthly), violating retention guarantees.

        Bug affects multiple tier interactions (see issue #32):
        - Weekly overrides daily: Nov 4 removed by weekly
        - Monthly overrides weekly: Oct 11 removed by monthly
        - Yearly overrides monthly: May 15 removed by yearly

        Once fixed, this test will pass and validate that each tier protects
        its threshold range from coarser tiers.
        """
        # Current: 2021-11-11 (Thursday)
        # Policies: keep_all=2, keep_daily=7, keep_weekly=4,
        #           keep_monthly=6, keep_yearly=3
        # Thresholds: all=Nov 9, daily=Nov 4, weekly=Oct 11,
        #             monthly=May 1, yearly=Jan 1 2018
        mock_datetime.now.return_value = datetime(2021, 11, 11)

        # Use dict for readability
        b = {}

        # Keep-all range (all backups after Nov 9)
        b["nov_11"] = add_backup("20211111_0300")
        b["nov_10_23h"] = add_backup("20211110_2300")
        b["nov_10_12h"] = add_backup("20211110_1200")
        b["nov_10_01h"] = add_backup("20211110_0100")
        b["nov_09"] = add_backup("20211109_0300")

        # Daily range (one per day: Nov 4-8)
        b["nov_08_dupe"] = add_backup("20211108_2200")  # removed: not oldest
        b["nov_08"] = add_backup("20211108_0100")
        b["nov_07"] = add_backup("20211107_0100")
        b["nov_06_dupe"] = add_backup("20211106_1800")  # removed: not oldest
        b["nov_06"] = add_backup("20211106_0100")
        b["nov_05"] = add_backup("20211105_0100")
        b["nov_04"] = add_backup("20211104_0100")  # BUG: removed by weekly!

        # Weekly range (one per week: Oct 11-Nov 7)
        b["nov_03"] = add_backup("20211103_0300")  # removed: same week
        b["nov_01_dupe"] = add_backup("20211101_1500")  # removed: not oldest
        b["nov_01"] = add_backup("20211101_0100")
        b["oct_31"] = add_backup("20211031_0100")  # removed: same week
        b["oct_25_dupe"] = add_backup("20211025_2000")  # removed: not oldest
        b["oct_25"] = add_backup("20211025_0100")
        b["oct_18"] = add_backup("20211018_0100")
        b["oct_11"] = add_backup("20211011_0100")  # BUG: removed by monthly!

        # Monthly range (one per month: May-Oct)
        b["oct_04"] = add_backup("20211004_0100")  # removed: same month
        b["oct_01"] = add_backup("20211001_0100")
        b["sep_15_dupe"] = add_backup("20210915_2000")  # removed: not oldest
        b["sep_15"] = add_backup("20210915_0100")
        b["aug_15"] = add_backup("20210815_0100")
        b["jul_15_dupe"] = add_backup("20210715_1200")  # removed: not oldest
        b["jul_15"] = add_backup("20210715_0100")
        b["jun_15"] = add_backup("20210615_0100")
        b["may_15"] = add_backup("20210515_0100")  # BUG: removed by yearly!

        # Yearly range (one per year: 2018-2021)
        b["apr_15"] = add_backup("20210415_0100")  # removed: same year
        b["jan_15_2021"] = add_backup("20210115_0100")
        b["dec_15_2020"] = add_backup("20201215_0100")  # removed: same year
        b["jul_15_2020"] = add_backup("20200715_0100")  # removed: same year
        b["jan_15_2020"] = add_backup("20200115_0100")
        b["dec_15_2019_dupe"] = add_backup("20191215_2300")  # removed: not oldest
        b["dec_15_2019"] = add_backup("20191215_0100")  # removed: same year
        b["jul_15_2019"] = add_backup("20190715_0100")  # removed: same year
        b["jan_15_2019"] = add_backup("20190115_0100")
        b["nov_15_2018"] = add_backup("20181115_0100")  # removed: same year
        b["jan_15_2018"] = add_backup("20180115_0100")

        # Beyond all thresholds
        b["jan_15_2017"] = add_backup("20170115_0100")  # removed: too old

        # Expected: each tier protects its range
        expected = [
            # keep_all: all 5 backups
            b["nov_11"], b["nov_10_23h"], b["nov_10_12h"],
            b["nov_10_01h"], b["nov_09"],

            # daily: oldest per day (Nov 4-8) = 5 backups
            # BUG: nov_04 missing - removed by weekly (same week as nov_03)
            b["nov_08"], b["nov_07"], b["nov_06"], b["nov_05"],
            b["nov_04"],

            # weekly: oldest per week (Oct 11 - Nov 7) = 4 backups
            # BUG: oct_11 missing - removed by monthly (same month as oct_01)
            b["nov_01"], b["oct_25"], b["oct_18"], b["oct_11"],

            # monthly: oldest per month (May-Oct) = 6 backups
            # BUG: may_15 missing - removed by yearly (same year as jan_15_2021)
            b["oct_01"], b["sep_15"], b["aug_15"],
            b["jul_15"], b["jun_15"],
            b["may_15"],

            # yearly: oldest per year (2018-2021) = 4 backups
            b["jan_15_2021"], b["jan_15_2020"],
            b["jan_15_2019"], b["jan_15_2018"],
        ]

        run_cleanup(keep_all=2, keep_daily=7, keep_weekly=4,
                   keep_monthly=6, keep_yearly=3)
        check_backups(expected)


class TestBackupLock:
    """Test suite for backup lock file functionality."""

    def test_lock_creation(self, backup_dir):
        """Test that lock file is created with current PID"""
        backup_dir.mkdir()
        result = bk.set_backups_lock(str(backup_dir))
        assert result

        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)
        assert os.path.exists(lock_path)

        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == os.getpid()

    def test_lock_prevents_concurrent_backup(self, backup_dir):
        """Test that second lock acquisition is blocked"""
        backup_dir.mkdir()
        # First lock should succeed
        result1 = bk.set_backups_lock(str(backup_dir))
        assert result1

        # The second lock should fail (same process trying to lock again)
        # Write a different PID to simulate another process
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))

        result2 = bk.set_backups_lock(str(backup_dir), force=False)
        assert not result2

    def test_stale_lock_is_removed(self, backup_dir):
        """Test that lock from non-existent process is cleaned up"""
        backup_dir.mkdir()
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)

        # Create lock with non-existent PID
        with open(lock_path, "w") as f:
            f.write("999999")

        # Lock should succeed by removing stale lock
        result = bk.set_backups_lock(str(backup_dir))
        assert result

        # Verify new lock has current PID
        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == os.getpid()

    def test_corrupted_lock_is_handled(self, backup_dir):
        """Test that corrupted lock file is handled gracefully"""
        backup_dir.mkdir()
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)

        # Create corrupted lock file (non-numeric content)
        with open(lock_path, "w") as f:
            f.write("not a number")

        # Lock should succeed by removing corrupted lock
        result = bk.set_backups_lock(str(backup_dir))
        assert result

        # Verify new lock has current PID
        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == os.getpid()

    def test_empty_lock_is_handled(self, backup_dir):
        """Test that empty lock file is handled gracefully"""
        backup_dir.mkdir()
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)

        # Create the empty lock file
        open(lock_path, "w").close()

        # Lock should succeed by removing empty lock
        result = bk.set_backups_lock(str(backup_dir))
        assert result

        # Verify new lock has current PID
        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == os.getpid()

    def test_lock_release(self, backup_dir):
        """Test that lock file is properly released"""
        backup_dir.mkdir()
        bk.set_backups_lock(str(backup_dir))
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)
        assert os.path.exists(lock_path)

        bk.release_backups_lock(str(backup_dir))
        assert not os.path.exists(lock_path)

    def test_release_nonexistent_lock(self, backup_dir):
        """Test that releasing non-existent lock doesn't raise error"""
        backup_dir.mkdir()
        # Should not raise any exception
        bk.release_backups_lock(str(backup_dir))

        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)
        assert not os.path.exists(lock_path)

    @mock.patch(f"{bk.__name__}.time.sleep")
    @mock.patch(f"{bk.__name__}.os.kill")
    @mock.patch(f"{bk.__name__}._pid_exists")
    def test_force_lock_with_sigterm_success(self, mock_pid_exists, mock_kill,
                                              mock_sleep, backup_dir):
        """Test force flag sends SIGTERM and acquires lock when process stops"""
        backup_dir.mkdir()
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)

        # Create lock with PID 12345
        with open(lock_path, "w") as f:
            f.write("12345")

        # Simulate process exists initially, then stops after SIGTERM
        mock_pid_exists.side_effect = [True, False]

        result = bk.set_backups_lock(str(backup_dir), force=True)
        assert result

        # Verify SIGTERM was sent
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)

        # Verify we waited after SIGTERM
        assert mock_sleep.call_count == 1
        mock_sleep.assert_any_call(5)

        # Verify new lock has current PID
        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == os.getpid()

    @mock.patch(f"{bk.__name__}.time.sleep")
    @mock.patch(f"{bk.__name__}.os.kill")
    @mock.patch(f"{bk.__name__}._pid_exists")
    def test_force_lock_requires_sigkill(self, mock_pid_exists, mock_kill,
                                         mock_sleep, backup_dir):
        """Test force flag escalates to SIGKILL when SIGTERM fails"""
        backup_dir.mkdir()
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)

        # Create lock with PID 12345
        with open(lock_path, "w") as f:
            f.write("12345")

        # Simulate process survives SIGTERM, dies after SIGKILL
        mock_pid_exists.side_effect = [True, True, False]

        result = bk.set_backups_lock(str(backup_dir), force=True)
        assert result

        # Verify both SIGTERM and SIGKILL were sent
        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        mock_kill.assert_any_call(12345, signal.SIGKILL)

        # Verify sleep was called twice (5s after SIGTERM, 1s after SIGKILL)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(5)
        mock_sleep.assert_any_call(1)

        # Verify new lock has current PID
        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == os.getpid()

    @mock.patch(f"{bk.__name__}.time.sleep")
    @mock.patch(f"{bk.__name__}.os.kill")
    @mock.patch(f"{bk.__name__}._pid_exists")
    def test_force_lock_handles_kill_failure(self, mock_pid_exists, mock_kill,
                                              mock_sleep, backup_dir):
        """Test force flag handles os.kill() failures gracefully"""
        backup_dir.mkdir()
        lock_path = os.path.join(str(backup_dir), bk.LOCK_FILE)

        # Create lock with PID 12345
        with open(lock_path, "w") as f:
            f.write("12345")

        # Simulate process exists
        mock_pid_exists.return_value = True

        # Simulate permission error when trying to kill
        mock_kill.side_effect = OSError("Permission denied")

        result = bk.set_backups_lock(str(backup_dir), force=True)
        assert not result  # Should fail

        # Verify SIGTERM was attempted
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)

        # Lock should still exist with old PID
        with open(lock_path, "r") as f:
            pid = int(f.read().strip())
        assert pid == 12345


class TestBackupIteration:
    """Tests for internal backup iteration and validation functions."""

    def test_is_backup_valid_backup(self, add_backup):
        """Test _is_backup recognizes valid backup directory"""
        backup = add_backup("20210101_120000")
        assert bk._is_backup(backup)

    def test_is_backup_missing_marker(self, backup_dir, tmp_path):
        """Test _is_backup rejects directory without marker"""
        backup_dir.mkdir()
        backup_path = backup_dir / "20210101_120000"
        backup_path.mkdir()
        # Create content but no marker
        (backup_path / "file.txt").write_text("content")

        entry = os.scandir(str(backup_dir))
        backup = next(entry)
        entry.close()
        assert not bk._is_backup(backup)

    def test_is_backup_only_marker_no_content(self, backup_dir):
        """Test _is_backup rejects directory with only marker file"""
        backup_dir.mkdir()
        backup_path = backup_dir / "20210101_120000"
        backup_path.mkdir()
        # Create only marker, no content
        marker_name = f"{bk.BACKUP_MARKER}_20210101_120000"
        (backup_path / marker_name).touch()

        entry = os.scandir(str(backup_dir))
        backup = next(entry)
        entry.close()
        assert not bk._is_backup(backup)

    def test_is_backup_invalid_name_format(self, backup_dir):
        """Test _is_backup rejects invalid directory name"""
        backup_dir.mkdir()
        backup_path = backup_dir / "not-a-backup"
        backup_path.mkdir()
        # Create marker and content
        marker_name = f"{bk.BACKUP_MARKER}_not-a-backup"
        (backup_path / marker_name).touch()
        (backup_path / "file.txt").write_text("content")

        entry = os.scandir(str(backup_dir))
        backup = next(entry)
        entry.close()
        assert not bk._is_backup(backup)

    def test_iterate_backups_empty_directory(self, backup_dir):
        """Test _iterate_backups on empty directory"""
        backup_dir.mkdir()
        backups = list(bk._iterate_backups(str(backup_dir)))
        assert backups == []

    def test_iterate_backups_mixed_contents(self, backup_dir, add_backup):
        """Test _iterate_backups filters non-backup entries"""
        # Create valid backups
        backup1 = add_backup("20210101_120000")
        backup2 = add_backup("20210102_120000")

        # Create invalid entries
        (backup_dir / "random_file.txt").write_text("not a backup")
        (backup_dir / "invalid_dir").mkdir()
        (backup_dir / bk.LOCK_FILE).touch()

        backups = sorted(bk._iterate_backups(str(backup_dir)),
                        key=lambda e: e.name)
        assert len(backups) == 2
        assert backups[0].name == backup1.name
        assert backups[1].name == backup2.name

    def test_iterate_backups_incomplete_backup(self, backup_dir):
        """Test _iterate_backups skips backup without marker"""
        backup_dir.mkdir()
        # Create complete backup
        complete = backup_dir / "20210101_120000"
        complete.mkdir()
        (complete / "file.txt").write_text("content")
        marker_name = f"{bk.BACKUP_MARKER}_20210101_120000"
        (complete / marker_name).touch()

        # Create incomplete backup (no marker)
        incomplete = backup_dir / "20210102_120000"
        incomplete.mkdir()
        (incomplete / "file.txt").write_text("content")

        backups = list(bk._iterate_backups(str(backup_dir)))
        assert len(backups) == 1
        assert backups[0].name == "20210101_120000"

    def test_get_latest_backup_returns_most_recent(self, backup_dir,
                                                     add_backup):
        """Test _get_latest_backup returns most recent backup"""
        add_backup("20210101_120000")
        add_backup("20210102_120000")
        latest = add_backup("20210103_120000")

        result = bk._get_latest_backup(str(backup_dir))
        assert result is not None
        assert result.name == latest.name

    def test_get_latest_backup_empty_directory(self, backup_dir):
        """Test _get_latest_backup returns None for empty directory"""
        backup_dir.mkdir()
        result = bk._get_latest_backup(str(backup_dir))
        assert result is None

    def test_get_latest_backup_no_valid_backups(self, backup_dir):
        """Test _get_latest_backup returns None with no valid backups"""
        backup_dir.mkdir()
        # Create incomplete backup
        incomplete = backup_dir / "20210101_120000"
        incomplete.mkdir()
        (incomplete / "file.txt").write_text("content")
        # no marker

        result = bk._get_latest_backup(str(backup_dir))
        assert result is None

    def test_set_backup_marker_creates_marker(self, backup_dir):
        """Test set_backup_marker creates marker file"""
        backup_dir.mkdir()
        backup_path = backup_dir / "20210101_120000"
        backup_path.mkdir()

        backup_entry = bk.fs.PseudoDirEntry(str(backup_path))
        bk.set_backup_marker(backup_entry)

        marker_name = f"{bk.BACKUP_MARKER}_20210101_120000"
        marker_path = backup_path / marker_name
        assert marker_path.exists()

    def test_set_backup_marker_idempotent(self, backup_dir):
        """Test set_backup_marker is idempotent"""
        backup_dir.mkdir()
        backup_path = backup_dir / "20210101_120000"
        backup_path.mkdir()

        backup_entry = bk.fs.PseudoDirEntry(str(backup_path))
        bk.set_backup_marker(backup_entry)
        # Call again - should not fail
        bk.set_backup_marker(backup_entry)

        marker_name = f"{bk.BACKUP_MARKER}_20210101_120000"
        marker_path = backup_path / marker_name
        assert marker_path.exists()
