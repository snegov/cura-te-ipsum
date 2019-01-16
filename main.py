#!/usr/bin/env python

import logging
import os
import sys


logging.basicConfig(level=logging.DEBUG)


def hardlink_dir(src_dir, dst_dir):
    """
    Make hardlink for a directory with all its content.
    :param src_dir: path to source directory
    :param dst_dir: path to target directory
    :return: None
    """
    logging.info(f'Recursive hardlinking: {src_dir} -> {dst_dir}')
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    def recursive_hardlink(src, dst):
        logging.debug(f'Creating directory: {src} -> {dst}')
        os.mkdir(dst)

        with os.scandir(src) as it:
            for ent in it:
                ent_dst_path = os.path.join(dst, ent.name)
                if ent.is_symlink():
                    symlink_target = os.readlink(ent.path)
                    logging.debug(f"Symlink to {symlink_target}: {ent.path} -> {ent_dst_path}")
                    os.symlink(symlink_target, ent_dst_path)
                    continue
                if ent.is_dir(follow_symlinks=False):
                    recursive_hardlink(ent.path, ent_dst_path)
                    continue
                if ent.is_file(follow_symlinks=False):
                    logging.debug(f"Hardlink file: {ent.path} -> {ent_dst_path}")
                    os.link(ent.path, ent_dst_path)
                    continue

    if not os.path.isdir(src_abs):
        logging.error(f"Error reading source directory: {src_dir}")
        raise RuntimeError(f"Error reading source directory: {src_dir}")

    if os.path.exists(dst_abs):
        logging.error(f"Destination already exists: {dst_dir}")
        raise RuntimeError(f'Destination already exists: {dst_dir}')

    recursive_hardlink(src_abs, dst_abs)
    return


def main():
    if len(sys.argv) != 3:
        print('Usage: %s SRC DST' % sys.argv[0])
        return 1

    hardlink_dir(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    sys.exit(main())
