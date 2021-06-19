import os
import os.path
import shutil
import string
import tempfile
import unittest

from spqr.curateipsum import fs


class CommonFSTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir_src = tempfile.TemporaryDirectory(prefix="source_")
        self.tmp_dir_dst = tempfile.TemporaryDirectory(prefix="dest_")
        self.src_dir = self.tmp_dir_src.name
        self.dst_dir = self.tmp_dir_dst.name

    def tearDown(self):
        self.tmp_dir_src.cleanup()
        self.tmp_dir_dst.cleanup()

    @staticmethod
    def create_file(parent_dir, prefix=None):
        fd, path = tempfile.mkstemp(prefix=prefix, dir=parent_dir)
        with open(fd, "w") as f:
            f.write(string.printable)
        return path

    @staticmethod
    def create_dir(parent_dir, prefix=None):
        return tempfile.mkdtemp(prefix=prefix, dir=parent_dir)

    def relpath(self, full_path):
        if full_path.startswith(self.src_dir):
            p_dir = self.src_dir
        elif full_path.startswith(self.dst_dir):
            p_dir = self.dst_dir
        else:
            raise RuntimeError(f"Path {full_path} is not src_dir nor dst_dir")

        return full_path[len(p_dir) + 1 :]


class TestHardlinkDir(CommonFSTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="source_")
        self.src_dir = self.tmp_dir.name
        self.dst_dir = self.src_dir + ".copy"

    def test_common_file(self):
        cf_path = self.create_file(self.src_dir)
        cf_relpath = self.relpath(cf_path)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        src_stat = os.lstat(cf_path)
        dst_stat = os.lstat(os.path.join(self.src_dir, cf_relpath))
        assert os.path.samestat(src_stat, dst_stat)
        assert src_stat.st_nlink == 2

    def test_relative_symlink_to_common_file(self):
        cf_relpath = self.relpath(self.create_file(self.src_dir))
        sl2cf_relpath = "symlink_to_common_file"
        os.chdir(self.src_dir)
        os.symlink(cf_relpath, sl2cf_relpath)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        # check link
        dst_sl2cf_path = os.path.join(self.dst_dir, sl2cf_relpath)
        assert os.readlink(dst_sl2cf_path) == cf_relpath

        # check stats
        src_stat = os.lstat(os.path.join(self.dst_dir, sl2cf_relpath))
        dst_stat = os.lstat(dst_sl2cf_path)
        assert os.path.samestat(src_stat, dst_stat)
        assert src_stat.st_nlink == 2

    def test_absolute_symlink_to_common_file(self):
        cf_path = self.create_file(self.src_dir)
        sl2cf_relpath = "symlink_to_common_file"
        sl2cf_path = os.path.join(self.src_dir, sl2cf_relpath)
        os.symlink(cf_path, sl2cf_path)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        # check link
        dst_sl2cf_path = os.path.join(self.dst_dir, sl2cf_relpath)
        assert os.readlink(dst_sl2cf_path) == cf_path

        # check stats
        src_stat = os.lstat(os.path.join(self.dst_dir, sl2cf_relpath))
        dst_stat = os.lstat(dst_sl2cf_path)
        assert os.path.samestat(src_stat, dst_stat)
        assert src_stat.st_nlink == 2

    def test_hardlink_to_common_file(self):
        cf_path = self.create_file(self.src_dir)
        hl2cf_relpath = "hardlink_to_common_file"
        hl2cf_path = os.path.join(self.src_dir, hl2cf_relpath)
        os.link(cf_path, hl2cf_path)

        fs.hardlink_dir(self.src_dir, self.dst_dir)

        src_cf_stat = os.lstat(cf_path)
        src_hl_stat = os.lstat(hl2cf_path)
        dst_hl_stat = os.lstat(os.path.join(self.dst_dir, hl2cf_relpath))

        assert os.path.samestat(src_cf_stat, dst_hl_stat)
        assert os.path.samestat(src_hl_stat, dst_hl_stat)
        assert src_cf_stat.st_nlink == 4

    def tearDown(self):
        self.tmp_dir.cleanup()
        shutil.rmtree(self.dst_dir, ignore_errors=True)


# TODO not finished
class TestRsync(CommonFSTestCase):
    @staticmethod
    def check_identical_file(file1, file2):
        st1 = os.lstat(file1)
        st2 = os.lstat(file2)

        assert st1.st_uid == st2.st_uid
        assert st1.st_gid == st2.st_gid
        assert st1.st_mode == st2.st_mode
        assert st1.st_mtime == st2.st_mtime
        assert st1.st_size == st2.st_size

    def test_dst_has_excess_file(self):
        dst_fpath = self.create_file(self.dst_dir)

        fs.rsync(self.src_dir, self.dst_dir)
        assert not os.path.lexists(dst_fpath)

    def test_dst_has_excess_symlink(self):
        dst_lpath = os.path.join(self.dst_dir, 'broken_symlink')
        os.symlink('broken_symlink', dst_lpath)

        fs.rsync(self.src_dir, self.dst_dir)
        assert not os.path.lexists(dst_lpath)

    def test_dst_has_excess_empty_dir(self):
        dst_dpath = self.create_dir(self.dst_dir)

        fs.rsync(self.src_dir, self.dst_dir)
        assert not os.path.lexists(dst_dpath)

    def test_dst_has_excess_nonempty_dir(self):
        dst_dpath = self.create_dir(self.dst_dir)
        self.create_file(dst_dpath)

        fs.rsync(self.src_dir, self.dst_dir)
        assert not os.path.lexists(dst_dpath)

    def test_dst_has_excess_nonempty_recursive_dir(self):
        dst_dpath = self.create_dir(self.dst_dir)
        nested_dpath = self.create_dir(dst_dpath)
        self.create_file(nested_dpath)

        fs.rsync(self.src_dir, self.dst_dir)
        assert not os.path.lexists(dst_dpath)

    def test_different_types_src_file_dst_dir(self):
        src_fpath = self.create_file(self.src_dir)
        dst_path = os.path.join(self.dst_dir, self.relpath(src_fpath))
        os.mkdir(dst_path)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_path)
        assert os.path.isfile(dst_path)

    def test_different_types_src_file_dst_symlink(self):
        src_fpath = self.create_file(self.src_dir)
        dst_path = os.path.join(self.dst_dir, self.relpath(src_fpath))
        os.symlink('broken_link', dst_path)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_path)
        assert os.path.isfile(dst_path)

    def test_different_types_src_symlink_dst_file(self):
        dst_path = self.create_file(self.dst_dir)
        src_lpath = os.path.join(self.src_dir, self.relpath(dst_path))
        os.symlink('broken_link', src_lpath)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_path)
        assert os.path.islink(dst_path)

    def test_different_types_src_symlink_dst_dir(self):
        dst_path = self.create_dir(self.dst_dir)
        src_lpath = os.path.join(self.src_dir, self.relpath(dst_path))
        os.symlink('broken_link', src_lpath)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_path)
        assert os.path.islink(dst_path)

    def test_different_types_src_dir_dst_file(self):
        src_dpath = self.create_dir(self.src_dir)
        dst_path = os.path.join(self.dst_dir, self.relpath(src_dpath))
        with open(dst_path, "w") as f:
            f.write(string.printable)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_path)
        assert os.path.isdir(dst_path)

    def test_different_types_src_dir_dst_symlink(self):
        src_dpath = self.create_dir(self.src_dir)
        dst_path = os.path.join(self.dst_dir, self.relpath(src_dpath))
        os.symlink('broken_link', dst_path)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_path)
        assert os.path.isdir(dst_path)

    def test_src_dst_same_inode(self):
        src_fpath = self.create_file(self.src_dir)
        dst_fpath = os.path.join(self.dst_dir, self.relpath(src_fpath))
        os.link(src_fpath, dst_fpath)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_fpath)
        src_stat = os.lstat(src_fpath)
        dst_stat = os.lstat(dst_fpath)
        assert src_stat.st_nlink == 1
        assert dst_stat.st_nlink == 1
        assert src_stat.st_ino != dst_stat.st_ino

    def test_src_dst_diff_size(self):
        src_fpath = self.create_file(self.src_dir)
        dst_fpath = os.path.join(self.dst_dir, self.relpath(src_fpath))
        with open(dst_fpath, "w") as df:
            df.write(string.printable * 2)

        fs.rsync(self.src_dir, self.dst_dir)
        assert os.path.lexists(dst_fpath)
        self.check_identical_file(src_fpath, dst_fpath)
