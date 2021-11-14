import os
import random
import string
import tempfile
from unittest import TestCase, mock
from datetime import datetime

from curateipsum import backup as bk, fs


class TestBackupCleanup(TestCase):
    def setUp(self) -> None:
        self.backup_dir = tempfile.TemporaryDirectory(prefix="backup_")

    def tearDown(self) -> None:
        self.backup_dir.cleanup()

    def _add_backup(self, backup_name: str) -> fs.PseudoDirEntry:
        backup = fs.PseudoDirEntry(os.path.join(self.backup_dir.name, backup_name))
        os.mkdir(backup.path)

        fd, path = tempfile.mkstemp(prefix="backup_file_", dir=backup.path)
        with open(fd, "w") as f:
            f.write(''.join(random.choices(string.printable, k=128)))
        return backup

    @staticmethod
    def _check_backup_not_empty(backup: fs.PseudoDirEntry) -> bool:
        return bool(os.listdir(backup.path))

    def _check_backups(self, expected_backups):
        backups_list = os.listdir(self.backup_dir.name)
        self.assertEqual(sorted(b.name for b in expected_backups),
                         sorted(backups_list))
        for b in expected_backups:
            self.assertTrue(self._check_backup_not_empty(b))

    def _run_cleanup(self, **kwargs):
        """ Run cleanup_old_backups with null parameters. """
        cleanup_kwargs = {
            "backup_dir": self.backup_dir.name,
            "dry_run": False,
            "keep_all": None,
            "keep_daily": None,
            "keep_weekly": None,
            "keep_monthly": None,
            "keep_yearly": None,
        }
        cleanup_kwargs.update(**kwargs)
        bk.cleanup_old_backups(**cleanup_kwargs)

    def test_no_backups(self):
        """ Test behaviour with no available backups """
        bk.cleanup_old_backups(self.backup_dir.name)
        self.assertFalse(os.listdir(self.backup_dir.name))

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_only_one_backup(self, mock_datetime):
        """ Test the only backup will not be removed in any case """
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        only_backup = self._add_backup("20010101_0000")
        self._run_cleanup(keep_all=1)
        self._check_backups([only_backup])

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_at_least_one_should_be_left(self, mock_datetime):
        """ Test at least one backup should be left """
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            self._add_backup("20211103_0300"),
            self._add_backup("20201216_0100"),
            self._add_backup("20200716_0100"),
            self._add_backup("20181116_0100"),
        ]
        expected_backups = [backups[0]]
        self._run_cleanup()
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_all_threshold_only(self, mock_datetime):
        """ Test threshold for keeping all backups """
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            self._add_backup("20211019_0300"),
            self._add_backup("20211017_0100"),
            self._add_backup("20211016_2300"),
        ]
        expected_backups = backups[:2]
        self._run_cleanup(keep_all=3)
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_daily_threshold_only(self, mock_datetime):
        """ Test threshold for keeping daily backups """
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            self._add_backup("20211019_0300"),
            self._add_backup("20211017_2100"),
            self._add_backup("20211017_0100"),
            self._add_backup("20211017_0030"),
            self._add_backup("20211016_2300"),
            self._add_backup("20211016_0100"),
        ]
        expected_backups = [backups[0], backups[3]]
        self._run_cleanup(keep_daily=3)
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_all_and_daily_thresholds(self, mock_datetime):
        """ Test threshold for keeping all and daily backups """
        mock_datetime.now.return_value = datetime(2021, 10, 20)
        backups = [
            self._add_backup("20211019_0300"),
            self._add_backup("20211017_0200"),
            self._add_backup("20211017_0100"),
            self._add_backup("20211016_2300"),
            self._add_backup("20211016_2200"),
            self._add_backup("20211015_2200"),
            self._add_backup("20211015_1500"),
            self._add_backup("20211015_0200"),
            self._add_backup("20211014_2200"),
            self._add_backup("20211014_2000"),
            self._add_backup("20211014_1232"),
        ]
        expected_backups = backups[0:3] + [backups[4]] + [backups[7]]
        self._run_cleanup(keep_all=3, keep_daily=5)
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_weekly_threshold_only(self, mock_datetime):
        """ Test threshold for keeping weekly backups """
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            self._add_backup("20211111_0300"),
            self._add_backup("20211110_0300"),
            self._add_backup("20211108_0100"),
            self._add_backup("20211107_2300"),
            self._add_backup("20211107_0100"),
            self._add_backup("20211031_0100"),
            self._add_backup("20211025_0100"),
            self._add_backup("20211024_0100"),
            self._add_backup("20211023_0100"),
            self._add_backup("20211022_0100"),
            self._add_backup("20211008_0100"),
            self._add_backup("20211007_0100"),
            self._add_backup("20211004_0100"),
            self._add_backup("20211003_0100"),
        ]
        expected_backups = [backups[2], backups[4], backups[6],
                            backups[9], backups[12]]
        self._run_cleanup(keep_weekly=5)
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_monthly_threshold_only(self, mock_datetime):
        """ Test threshold for keeping monthly backups """
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            self._add_backup("20211103_0300"),
            self._add_backup("20211019_0300"),
            self._add_backup("20211017_2100"),
            self._add_backup("20211017_0100"),
            self._add_backup("20210916_2300"),
            self._add_backup("20210916_0100"),
            self._add_backup("20210816_0100"),
            self._add_backup("20210810_0000"),
            self._add_backup("20210716_0100"),
        ]
        expected_backups = [backups[0], backups[3], backups[5], backups[7]]
        self._run_cleanup(keep_monthly=3)
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_keep_yearly_threshold_only(self, mock_datetime):
        """ Test threshold for keeping yearly backups """
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            self._add_backup("20211103_0300"),
            self._add_backup("20210810_0000"),
            self._add_backup("20210716_0100"),
            self._add_backup("20201216_0100"),
            self._add_backup("20200716_0100"),
            self._add_backup("20190316_0100"),
            self._add_backup("20181116_0100"),
        ]
        expected_backups = [backups[2], backups[4], backups[5], backups[6]]
        self._run_cleanup(keep_yearly=3)
        self._check_backups(expected_backups)

    @mock.patch(f"{bk.__name__}.datetime", wraps=datetime)
    def test_dry_run(self, mock_datetime):
        """ Test dry run does not remove anything """
        mock_datetime.now.return_value = datetime(2021, 11, 11)
        backups = [
            self._add_backup("20211103_0300"),
            self._add_backup("20210810_0000"),
            self._add_backup("20210716_0100"),
            self._add_backup("20200716_0100"),
            self._add_backup("20181116_0100"),
        ]
        self._run_cleanup(keep_all=2, dry_run=True)
        self._check_backups(backups)
