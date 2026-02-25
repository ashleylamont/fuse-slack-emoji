#!/usr/bin/env python

#    Copyright (C) 2006  Andrew Straw  <strawman@astraw.com>
#
#    This program can be distributed under the terms of the GNU LGPL.
#    See the file COPYING.
#

import os, stat, errno

from file_system.fs_operations import SlackBasedFileSystem
from storage_backend.slack_mock import SlackMockInterface

# pull in some spaghetti to make this stuff work without fuse-py being installed
try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse
from fuse import Fuse


if not hasattr(fuse, '__version__'):
    raise RuntimeError("your fuse-py doesn't know of fuse.__version__, probably it's too old.")

fuse.fuse_python_api = (0, 2)

class SlackFS(Fuse):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

        self.slack_mock = SlackMockInterface()
        self.slack_fs = SlackBasedFileSystem(self.slack_mock)

    def getattr(self, path):
        try:
            result = self.slack_fs.get_attr(path)
            print("Returning from getattr", result)
            return result
        except FileNotFoundError:
            return -errno.ENOENT
        except Exception as error:
            print("Error in getattr", error)


    def readdir(self, path, offset):
        print("Calling readdir")
        # todo: work out what offset does
        for r in  self.slack_fs.read_dir(path):
            yield fuse.Direntry(r)

    def open(self, path, flags):
        # todo: use flags, and also don't just jankily use read_file
        try:
            self.slack_fs.read_file(path, 0, 0)
        except FileNotFoundError:
            return -errno.ENOENT

    def read(self, path, size, offset):
        try:
            return self.slack_fs.read_file(path, size, offset)
        except FileNotFoundError:
            return -errno.ENOENT

    def mkdir(self, path, mode):
        try:
            self.slack_fs.mkdir(path, mode)
        except FileNotFoundError:
            return -errno.ENOENT

    def unlink(self, path):
        try:
            self.slack_fs.unlink(path)
        except FileNotFoundError:
            return -errno.ENOENT

    def rmdir(self, path):
        try:
            self.slack_fs.rmdir(path)
        except FileNotFoundError:
            return -errno.ENOENT

    def create(self, path, mode, file_info):
        # todo: wtf is file_info
        try:
            self.slack_fs.create_file(path, mode)
        except FileNotFoundError:
            return -errno.ENOENT

    def write(self, path, buffer, offset):
        try:
            self.slack_fs.write_file(path, buffer, offset)
        except FileNotFoundError:
            return -errno.ENOENT

def main():
    usage="""
Userspace slack emoji FS

""" + Fuse.fusage
    server = SlackFS(version="%prog " + fuse.__version__,
                     usage=usage,
                     dash_s_do='setsingle')

    server.parse(errex=1)
    server.main()

if __name__ == '__main__':
    main()