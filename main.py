#!/usr/bin/env python

import logging
import os
import sys


logging.basicConfig(level=logging.DEBUG)


def hardlink_dir(src_dir, dst_dir):
    logging.info(f'Recursive hardlinking: {src_dir} -> {dst_dir}')
    src_abs = os.path.abspath(src_dir)
    dst_abs = os.path.abspath(dst_dir)

    if os.path.isdir(dst_abs):
        logging.error(f"Destination directory already exists: {dst_dir}")
        raise RuntimeError(f'dst dir already exists: {dst_dir}')

    recursive_hardlink(src_abs, dst_abs)
    return

def recursive_hardlink(src, dst):
    logging.debug(f'Hardlink: {src} -> {dst}')
    logging.debug(f'Creating top directory: {dst}')
    os.mkdir(dst)

    with os.scandir(src) as it:
        for ent in it:
            if ent.is_symlink():
                logging.error(f'{ent.path}: symlink, skipping')
                continue
            if ent.is_dir(follow_symlinks=False):
                recursive_hardlink(ent.path, os.path.join(dst, ent.name))
                continue
            if ent.is_file(follow_symlinks=False):
                os.link(ent.path, os.path.join(dst, ent.name), follow_symlinks=False)




def main():
    if len(sys.argv) != 3:
        print('Usage: %s SRC DST' % sys.argv[0])

    hardlink_dir(sys.argv[1], sys.argv[2])

if __name__ == '__main__':
    sys.exit(main())