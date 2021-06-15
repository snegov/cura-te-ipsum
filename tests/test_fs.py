import os
import os.path
import shutil
import string
import tempfile
import unittest

from spqr.curateipsum import fs


class TestHardlinkDir(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.src_dir = self.tmp_dir.name
        self.dst_dir = self.src_dir + ".copy"

        # common_file
        self.cf_name = "common_file"
        self.cf = os.path.join(self.src_dir, self.cf_name)
        with open(self.cf, "w") as f:
            f.write(string.printable)

        # symlink to common file
        self.sl2cf_name = "symlink_to_common_file"
        self.sl2cf = os.path.join(self.src_dir, self.sl2cf_name)
        os.symlink(self.cf, self.sl2cf)

        # hardlink to common file
        self.hl2cf_name = "hardlink_to_common_file"
        self.hl2cf = os.path.join(self.src_dir, self.hl2cf_name)
        os.link(self.cf, self.hl2cf)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

    def test_common_file(self):
        src_stat = os.lstat(self.cf)
        dst_stat = os.lstat(os.path.join(self.dst_dir, self.cf_name))
        self.assertTrue(os.path.samestat(src_stat, dst_stat))

    def test_symlink_to_common_file(self):
        dst_sl2cf_path = os.path.join(self.dst_dir, self.sl2cf_name)
        self.assertEqual(os.readlink(dst_sl2cf_path), self.cf)

    def test_hardlink_to_common_file(self):
        src_stat = os.lstat(self.hl2cf)
        dst_stat = os.lstat(os.path.join(self.dst_dir, self.hl2cf_name))
        self.assertTrue(os.path.samestat(src_stat, dst_stat))

    @classmethod
    def tearDownClass(self):
        self.tmp_dir.cleanup()
        shutil.rmtree(self.dst_dir, ignore_errors=True)
