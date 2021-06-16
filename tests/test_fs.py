import os
import os.path
import shutil
import string
import tempfile
import unittest

from spqr.curateipsum import fs


class TestHardlinkDir(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.src_dir = self.tmp_dir.name
        self.dst_dir = self.src_dir + ".copy"

    def _create_common_file(self):
        cf_relpath = "common_file"
        cf_path = os.path.join(self.src_dir, cf_relpath)
        with open(cf_path, "w") as f:
            f.write(string.printable)
        return cf_relpath

    def test_common_file(self):
        cf_relpath = self._create_common_file()

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        src_stat = os.lstat(os.path.join(self.dst_dir, cf_relpath))
        dst_stat = os.lstat(os.path.join(self.src_dir, cf_relpath))
        self.assertTrue(os.path.samestat(src_stat, dst_stat))
        self.assertEqual(src_stat.st_nlink, 2)

    def test_relative_symlink_to_common_file(self):
        cf_relpath = self._create_common_file()
        sl2cf_relpath = "symlink_to_common_file"
        os.chdir(self.src_dir)
        os.symlink(cf_relpath, sl2cf_relpath)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        # check link
        dst_sl2cf_path = os.path.join(self.dst_dir, sl2cf_relpath)
        self.assertEqual(os.readlink(dst_sl2cf_path), cf_relpath)

        # check stats
        src_stat = os.lstat(os.path.join(self.dst_dir, sl2cf_relpath))
        dst_stat = os.lstat(dst_sl2cf_path)
        self.assertTrue(os.path.samestat(src_stat, dst_stat))
        self.assertEqual(src_stat.st_nlink, 2)

    def test_absolute_symlink_to_common_file(self):
        cf_relpath = self._create_common_file()
        cf_path = os.path.join(self.src_dir, cf_relpath)
        sl2cf_relpath = "symlink_to_common_file"
        sl2cf_path = os.path.join(self.src_dir, sl2cf_relpath)
        os.symlink(cf_path, sl2cf_path)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        # check link
        dst_sl2cf_path = os.path.join(self.dst_dir, sl2cf_relpath)
        self.assertEqual(os.readlink(dst_sl2cf_path), cf_path)

        # check stats
        src_stat = os.lstat(os.path.join(self.dst_dir, sl2cf_relpath))
        dst_stat = os.lstat(dst_sl2cf_path)
        self.assertTrue(os.path.samestat(src_stat, dst_stat))
        self.assertEqual(src_stat.st_nlink, 2)

    def test_hardlink_to_common_file(self):
        cf_relpath = self._create_common_file()
        cf_path = os.path.join(self.src_dir, cf_relpath)
        hl2cf_relpath = "hardlink_to_common_file"
        hl2cf_path = os.path.join(self.src_dir, hl2cf_relpath)
        os.link(cf_path, hl2cf_path)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        src_cf_stat = os.lstat(cf_path)
        src_hl_stat = os.lstat(hl2cf_path)
        dst_hl_stat = os.lstat(os.path.join(self.dst_dir, hl2cf_relpath))

        self.assertTrue(os.path.samestat(src_cf_stat, dst_hl_stat))
        self.assertTrue(os.path.samestat(src_hl_stat, dst_hl_stat))
        self.assertEqual(src_cf_stat.st_nlink, 4)

    def tearDown(self):
        self.tmp_dir.cleanup()
        shutil.rmtree(self.dst_dir, ignore_errors=True)
