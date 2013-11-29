import fileinfo
import errno
import os
import os.path
import platform
# Python 2 needs to use the StringIO module to have a file-like object
# that you can write strings to and results in a string; in Python 3 we need to
# get this from the io module
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
import tempfile
import unittest

mock_ioctl_exception = None
def mock_ioctl(fd, opt, arg, mutate_flag=False):
    if mock_ioctl_exception:
        raise mock_ioctl_exception

# test our utility functions
class UtilityTests(unittest.TestCase):
    # TODO: extend string type to add isprintable or not for testing
    def _test_8bit_ascii_simple(self):
        for n in range(0x7f, 0x100):
            self.assertEqual("\\x%02x" % n, fileinfo.escape_filename(chr(n)))
    def _test_8bit_ascii_fancy(self):
        for n in range(0x7f, 0x100):
            c = chr(n)
            if c.isprintable():
                self.assertEqual(c, fileinfo.escape_filename(c))
            else:
                self.assertEqual("\\x%02x" % n, fileinfo.escape_filename(c))
    test_chars = (0x100, 0x101, 0x1fe, 0x1ff, 0x200, 0x201, 0x1000, 0x1001)
    test_nonprintable_chars = (0xffe, 0xfff, 0xfffe, 0xffff)
    test_big_chars = (0x10000, 0x10001, 0x20000, 0x20001)
    # characters must be in range(0x110000)
    test_big_nonprintable_chars = (0x1fffe, 0x1ffff, 0x2fffe, 0x2ffff,
                                   0xffffe, 0xfffff, 0x100000, 0x100001,
                                   0x10fffe,0x10ffff)
    def test_escape_filename(self):
        self.assertEqual("", fileinfo.escape_filename(""))
        self.assertEqual("a", fileinfo.escape_filename("a"))
        longString = "a" * 100000
        self.assertEqual(longString, fileinfo.escape_filename(longString))
        self.assertEqual("\\x00", fileinfo.escape_filename("\x00"))
        for n in list(range(0, 32)) + [92,]:
            self.assertEqual("\\x%02x" % n, fileinfo.escape_filename(chr(n)))
        for n in list(range(32, 92)) + list(range(93, 126)):
            self.assertEqual(chr(n), fileinfo.escape_filename(chr(n)))
        if not hasattr("", "isprintable"):
            self._test_8bit_ascii_simple()
            for n in self.test_chars + self.test_nonprintable_chars:
                self.assertEqual("\\u%04x" % n, 
                                 fileinfo.escape_filename(unichr(n)))
            for n in self.test_big_chars + self.test_big_nonprintable_chars:
                self.assertEqual("\\U%08x" % n, 
                                 fileinfo.escape_filename(unichr(n)))
        else:
            self._test_8bit_ascii_fancy()
            for n in self.test_chars + self.test_big_chars:
                self.assertEqual(chr(n), fileinfo.escape_filename(chr(n)))
            for n in self.test_nonprintable_chars:
                self.assertEqual("\\u%04x" % n, 
                                 fileinfo.escape_filename(chr(n)))
            for n in self.test_big_chars:
                self.assertEqual(chr(n), fileinfo.escape_filename(chr(n)))
            for n in self.test_big_nonprintable_chars:
                self.assertEqual("\\U%08x" % n, 
                                 fileinfo.escape_filename(chr(n)))
        self.assertEqual("\\x00y", fileinfo.escape_filename("\x00y"))
        self.assertEqual("z\\x00", fileinfo.escape_filename("z\x00"))

    def test_file_time(self):
        # verify basic functionality
        self.assertEqual("19700101000000", fileinfo.file_time(0, 0))
        # check that we properly drop off trailing zeros
        self.assertEqual("19700101000000.000000001", fileinfo.file_time(0, 1))
        self.assertEqual("19700101000000.00000001", fileinfo.file_time(0, 10))
        self.assertEqual("19700101000000.0000001", fileinfo.file_time(0, 100))
        self.assertEqual("19700101000000.000001", fileinfo.file_time(0, 1000))
        self.assertEqual("19700101000000.00001", fileinfo.file_time(0, 10000))
        self.assertEqual("19700101000000.0001", fileinfo.file_time(0, 100000))
        self.assertEqual("19700101000000.001", fileinfo.file_time(0, 1000000))
        self.assertEqual("19700101000000.01", fileinfo.file_time(0, 10000000))
        self.assertEqual("19700101000000.1", fileinfo.file_time(0, 100000000))
        # check that we have our proper conversions for Y/m/d H:M:S
        self.assertEqual("19700101000001", fileinfo.file_time(1, 0))
        self.assertEqual("19700101000059", fileinfo.file_time(59, 0))
        self.assertEqual("19700101000100", fileinfo.file_time(60, 0))
        self.assertEqual("19700101005959", fileinfo.file_time(3599, 0))
        self.assertEqual("19700101010000", fileinfo.file_time(3600, 0))
        self.assertEqual("19700101010001", fileinfo.file_time(3601, 0))
        self.assertEqual("19700101235959", fileinfo.file_time(86399, 0))
        self.assertEqual("19700102000000", fileinfo.file_time(86400, 0))
        self.assertEqual("19700102000001", fileinfo.file_time(86401, 0))
        self.assertEqual("19700131235959", fileinfo.file_time(2678399, 0))
        self.assertEqual("19700201000000", fileinfo.file_time(2678400, 0))
        self.assertEqual("19700201000001", fileinfo.file_time(2678401, 0))
        self.assertEqual("19701231235959", fileinfo.file_time(31535999, 0))
        self.assertEqual("19710101000000", fileinfo.file_time(31536000, 0))
        self.assertEqual("19710101000001", fileinfo.file_time(31536001, 0))

    def test_file_time_details(self):
        class st_with_times:
            def __init__(self, 
                         atime, atime_ns, ctime, ctime_ns, mtime, mtime_ns):
                self.st_atime = atime
                if atime_ns is not None:
                    self.st_atime_ns = atime_ns
                self.st_ctime = ctime
                if ctime_ns is not None:
                    self.st_ctime_ns = ctime_ns
                self.st_mtime = mtime
                if mtime_ns is not None:
                    self.st_mtime_ns = mtime_ns
        # test without any nsec values
        st = st_with_times(0, None, 315532800, None, 631152000, None)
        self.assertEqual(("19700101000000",
                          "19800101000000",
                          "19900101000000"),
                         fileinfo.file_time_details(st))
        # test wth 0 nsec values
        st = st_with_times(0, 0, 315532800, 0, 631152000, 0)
        self.assertEqual(("19700101000000",
                          "19800101000000",
                          "19900101000000"),
                         fileinfo.file_time_details(st))
        # test with non-0 nsec values
        st = st_with_times(0, 100000000, 315532800, 10000000, 631152000, 1)
        self.assertEqual(("19700101000000.1", 
                          "19800101000000.01", 
                          "19900101000000.000000001"),
                         fileinfo.file_time_details(st))
        # test with floating point values
        st = st_with_times(0.1, None, 315532800.01, None, 0.000001, None)
        self.assertEqual(("19700101000000.1", 
                          "19800101000000.01", 
                          "19700101000000.000001"),
                         fileinfo.file_time_details(st))
        # test with floating point values that lose precision
        st = st_with_times(0.123456789, None, 0.01, None, 0.000001, None)
        self.assertEqual(("19700101000000.123457", 
                          "19700101000000.01", 
                          "19700101000000.000001"),
                         fileinfo.file_time_details(st))

    # ideally we would of course mount a FAT file system and a non-FAT
    # file system and use those to test the function, but that is not
    # really possible in a generic way, and falls outside of the scope
    # of unit tests
    def test_is_fatfs_file(self):
        # this only works in Linux (skipping tests is Python 2.7+ only, so 
        # we just put a check here)
        if not (platform.system() == 'Linux'): return
        # install a mock ioctl() function
        save_ioctl = fileinfo.fcntl.ioctl
        try:
            fileinfo.fcntl.ioctl = mock_ioctl
            global mock_ioctl_exception
            # if no exception is raised, then we assume that we have a FAT
            # file system
            mock_ioctl_exception = None
            self.assertTrue(fileinfo.is_fatfs_file("."))
            # if we get a ENOTTY or ENOSYS exception, then we do NOT have
            # a FAT file system
            err = IOError()
            err.errno = errno.ENOTTY
            mock_ioctl_exception = err
            self.assertFalse(fileinfo.is_fatfs_file("."))
            err = IOError()
            err.errno = errno.ENOSYS
            mock_ioctl_exception = err
            self.assertFalse(fileinfo.is_fatfs_file("."))
            # and insure that we pass through other exceptions
            err = IOError()
            err.errno = errno.EACCES
            mock_ioctl_exception = err
            self.assertRaises(IOError, fileinfo.is_fatfs_file, ".")
        finally:
            # restore our real ioctl() function
            fileinfo.fcntl.ioctl = save_ioctl

    def test_make_type_unicode(self):
        # This one is tricky to test, since the function is a single line 
        # based on implementation details. However the isdecimal() function
        # is not presend in Python 2.x strings but *is* present in Python
        # 2.x unicode objects. It is also conveniently present in Python 3
        # strings.
        foo = fileinfo.make_type_unicode("bar")
        self.assertEqual(foo, "bar")
        self.assertTrue(hasattr(foo, 'isdecimal'))

# test the classes that carry information around and output it
class InfoTests(unittest.TestCase):
    def test_chdir_info(self):
        # create a directory to test
        dir_name = tempfile.mkdtemp()
        try:
            # make a chdir_info object
            info = fileinfo.chdir_info(dir_name)
            # output into a string buffer
            out = StringIO()
            err = StringIO()
            prev_stat_val = "should_be_unchanged"
            prev_stat = info.output(out, err, prev_stat_val)
            # confirm that all of our values are as expected
            self.assertEqual(prev_stat_val, prev_stat)
            self.assertEqual(out.getvalue(), "!" + dir_name + "\n")
            self.assertEqual(err.getvalue(), "")
        finally:
            os.rmdir(dir_name)

    def test_chdir_info_fat(self):
        # this only works in Linux (skipping tests is Python 2.7+ only, so 
        # we just put a check here)
        if not (platform.system() == 'Linux'): return
        dir_name = tempfile.mkdtemp()
        # put a mock version of is_fatfs_file() in place
        save_is_fatfs_file = fileinfo.is_fatfs_file
        try:
            fileinfo.is_fatfs_file = lambda x: True
            # make a chdir_info object
            info = fileinfo.chdir_info(dir_name)
            # output into a string buffer
            out = StringIO()
            err = StringIO()
            prev_stat_val = "should_be_unchanged"
            prev_stat = info.output(out, err, prev_stat_val)
            # confirm that all of our values are as expected
            self.assertEqual(prev_stat_val, prev_stat)
            self.assertEqual(out.getvalue(), ":" + dir_name + "\n")
            self.assertEqual(err.getvalue(), "")
        finally:
            fileinfo.is_fatfs_file = save_is_fatfs_file
            os.rmdir(dir_name)

    def test_cached_info(self):
        # make a chdir_info object
        class dummy_stat:
            def __init__(self):
                self.st_ino = 42
        stat_val = dummy_stat()
        info = fileinfo.cached_info('foo', stat_val)
        # output into a string buffer
        out = StringIO()
        err = StringIO()
        prev_stat_val = "should_not_be_used"
        prev_stat = info.output(out, err, prev_stat_val)
        # confirm that all of our values are as expected
        self.assertEqual(stat_val, prev_stat)
        self.assertEqual(out.getvalue(), "i42\n>foo\n")
        self.assertEqual(err.getvalue(), "")

    def test_file_info(self):
        # check our initializer
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = os.lstat(full_path)
        info = fileinfo.file_info(file_name, full_path, stat)

        self.assertEqual(file_name, info.file_name)
        self.assertEqual(full_path, info.full_path)
        self.assertIs(stat, info.stat)
        self.assertIsNone(info.encoded_hash)
        self.assertIsNone(info.hashing_error)
        

if __name__ == '__main__':
    unittest.main()
