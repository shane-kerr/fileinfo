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
try:
    import Queue
except ImportError:
    import queue as Queue
import base64

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
        # check hash setting
        info.set_hash("fubar")
        self.assertEqual(info.encoded_hash, "fubar")
        # check hash error setting
        info.set_hashing_error("baz")
        self.assertEqual(info.hashing_error, "baz")

    class mock_stat:
        def __init__(self):
            self.st_mode = 0o640
            self.st_ino = 1234
            self.st_nlink = 1
            self.st_uid = 0
            self.st_gid = 0
            self.st_size = 0
            self.st_atime = 0
            self.st_atime_ns = 0
            self.st_ctime = 0
            self.st_ctime_ns = 0
            self.st_mtime = 0
            self.st_mtime_ns = 0
            self.st_rdev = 0
            self.st_flags = 0

    def test_file_info_output(self):
        # try hashing error with a bogus value
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = os.lstat(full_path)
        info = fileinfo.file_info(file_name, full_path, stat)
        info.set_hashing_error("bogus")
        out = StringIO()
        err = StringIO()
        next_stat = info.output(out, err, None)
        self.assertEqual(next_stat, info.stat)
        self.assertEqual(err.getvalue(), "Error with '.': bogus\n")
        # try hashing error with an actual exception
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = os.lstat(full_path)
        info = fileinfo.file_info(file_name, full_path, stat)
        try:
            open("/nosuchfile", "r")
        except Exception as e:
            hashing_error = e
        info.set_hashing_error(hashing_error)
        out = StringIO()
        err = StringIO()
        next_stat = info.output(out, err, None)
        self.assertEqual(next_stat, info.stat)
        self.assertEqual(err.getvalue(),
                         "Error with '.': [ENOENT] No such file or directory\n")
        # okay, now lets check our non-error output with None prev_stat
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = self.mock_stat()
        info = fileinfo.file_info(file_name, full_path, stat)
        out = StringIO()
        err = StringIO()
        next_stat = info.output(out, err, None)
        self.assertEqual(next_stat, info.stat)
        self.assertEqual(out.getvalue(),
          "m640\ni1234\nn1\nu0\ng0\ns0\nC19700101000000\nA19700101000000\n>.\n")
        # prev_stat, with all attributes different from prev_stat
        # (this will force a full output of all values)
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = self.mock_stat()
        info = fileinfo.file_info(file_name, full_path, stat)
        out = StringIO()
        err = StringIO()
        prev_stat = self.mock_stat()
        prev_stat.st_mode = stat.st_mode + 1
        prev_stat.st_ino = stat.st_ino + 1
        prev_stat.st_nlink = stat.st_nlink + 1
        prev_stat.st_uid = stat.st_uid + 1
        prev_stat.st_gid = stat.st_gid + 1
        prev_stat.st_size = stat.st_size + 1
        prev_stat.st_atime_ns =  stat.st_atime_ns + 1
        prev_stat.st_ctime_ns =  stat.st_ctime_ns + 1
        prev_stat.st_mtime_ns =  stat.st_mtime_ns + 1
        next_stat = info.output(out, err, prev_stat)
        self.assertEqual(next_stat, info.stat)
        self.assertEqual(out.getvalue(),
          "m640\ni1234\nn1\nu0\ng0\ns0\nC19700101000000\nA19700101000000\n>.\n")
        # prev_stat, with all attributes identical to prev_stat
        # (this will force a minimal output of values)
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = self.mock_stat()
        info = fileinfo.file_info(file_name, full_path, stat)
        out = StringIO()
        err = StringIO()
        prev_stat = self.mock_stat()
        next_stat = info.output(out, err, prev_stat)
        self.assertEqual(next_stat, info.stat)
        self.assertEqual(out.getvalue(),
          ">.\n")
        # okay, now run and get mtime, rdev, flags, and hash
        file_name = '.'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = self.mock_stat()
        info = fileinfo.file_info(file_name, full_path, stat)
        out = StringIO()
        err = StringIO()
        prev_stat = self.mock_stat()
        stat.st_mtime_ns = stat.st_ctime_ns + 1
        stat.st_rdev = 1
        stat.st_flags = 2
        info.set_hash("a hash")
        next_stat = info.output(out, err, prev_stat)
        self.assertEqual(next_stat, info.stat)
        self.assertEqual(out.getvalue(),
          "M19700101000000.000000001\nr1\nf2\n#a hash\n>.\n")

# simulate a failure of O_NOATIME by creating EPERM when opening a file
org_os_open = None
def mock_os_open(fname, flags):
    noatime = getattr(os, 'O_NOATIME', 0)
    if (flags & noatime) != 0:
        raise OSError(errno.EPERM, "Permission denied: '%s'" % fname)
    return org_os_open(fname, flags)

# test the serializer and checksum tasks
class TaskTests(unittest.TestCase):
    class mock_info:
        def __init__(self, message):
            self.message = message
        def output(self, out, err, prev_stat):
            out.write(self.message + "\n")
            return prev_stat

    def test_serializer(self):
        # test a serializer with no entries sent
        q = Queue.Queue()
        q.put(None)
        out = StringIO()
        fileinfo.serializer(q, 1, out)
        self.assertEqual(out.getvalue(), '')
        # try a single entry
        q = Queue.Queue()
        q.put((0, self.mock_info("single")))
        q.put(None)
        out = StringIO()
        fileinfo.serializer(q, 1, out)
        self.assertEqual(out.getvalue(), 'single\n')
        # now try several entries
        q = Queue.Queue()
        q.put((0, self.mock_info("a")))
        q.put((1, self.mock_info("b")))
        q.put((2, self.mock_info("c")))
        q.put((3, self.mock_info("d")))
        q.put((4, self.mock_info("e")))
        q.put(None)
        out = StringIO()
        fileinfo.serializer(q, 1, out)
        self.assertEqual(out.getvalue(), 'a\nb\nc\nd\ne\n')
        # now try several entries, out of order
        q = Queue.Queue()
        q.put((0, self.mock_info("a")))
        q.put((4, self.mock_info("e")))
        q.put((2, self.mock_info("c")))
        q.put((3, self.mock_info("d")))
        q.put((1, self.mock_info("b")))
        q.put(None)
        out = StringIO()
        fileinfo.serializer(q, 1, out)
        self.assertEqual(out.getvalue(), 'a\nb\nc\nd\ne\n')
        # finally, simulate our complete system by having multiple generators
        q = Queue.Queue()
        q.put((0, self.mock_info("a")))
        q.put((4, self.mock_info("e")))
        q.put((2, self.mock_info("c")))
        q.put((3, self.mock_info("d")))
        q.put((1, self.mock_info("b")))
        q.put(None)
        q.put(None)
        q.put(None)
        q.put(None)
        out = StringIO()
        fileinfo.serializer(q, 4, out)
        self.assertEqual(out.getvalue(), 'a\nb\nc\nd\ne\n')

    def test_get_checksum(self):
        # confirm that our checksum works
        temp_file = tempfile.NamedTemporaryFile()
        temp_file.write(b"some data\n")
        temp_file.flush()
        file_name = os.path.basename(temp_file.name)
        full_path = temp_file.name
        stat = os.lstat(full_path)
        info = fileinfo.file_info(file_name, full_path, stat)
        self.assertIsNone(info.encoded_hash)
        result = fileinfo.get_checksum(info)
        self.assertEqual(result, info)
        hash_val = base64.b64decode(info.encoded_hash)
        self.assertEqual(len(hash_val), 28)
        self.assertIsNone(info.hashing_error)
        # check with an open error (no permission to open file)
        old_mode = stat.st_mode
        os.chmod(temp_file.name, 0)
        stat = os.lstat(full_path)
        info = fileinfo.file_info(file_name, full_path, stat)
        self.assertIsNone(info.encoded_hash)
        result = fileinfo.get_checksum(info)
        os.chmod(temp_file.name, old_mode)
        self.assertEqual(result, info)
        self.assertIsNone(info.encoded_hash)
        self.assertEqual(info.hashing_error.errno, errno.EACCES)

        # test our hack to detect O_NOATIME file-system errors
        global org_os_open
        file_name = '/etc/passwd'
        full_path = os.path.normpath(os.path.join(os.getcwd(), file_name))
        stat = os.lstat(full_path)
        info = fileinfo.file_info(file_name, full_path, stat)
        self.assertIsNone(info.encoded_hash)

        org_os_open = fileinfo.os.open
        fileinfo.os.open = mock_os_open
        result = fileinfo.get_checksum(info)
        fileinfo.os.open = org_os_open

        self.assertEqual(result, info)
        hash_val = base64.b64decode(info.encoded_hash)
        self.assertEqual(len(hash_val), 28)
        self.assertIsNone(info.hashing_error)
        # TODO: verify actual value...

    def test_checksum_generator(self):
        # test a checksum generator that gets no input
        q_in = Queue.Queue()
        q_in.put(None)
        q_out = Queue.Queue()
        fileinfo.checksum_generator(q_in, q_out)
        self.assertIsNone(q_out.get_nowait())
        self.assertTrue(q_out.empty())
        # test a checksum generator that gets some files
        q_in = Queue.Queue()
        temp_file1 = tempfile.NamedTemporaryFile()
        file_name = os.path.basename(temp_file1.name)
        full_path = temp_file1.name
        stat = os.lstat(full_path)
        info1 = fileinfo.file_info(file_name, full_path, stat)
        q_in.put((0, info1))
        temp_file2 = tempfile.NamedTemporaryFile()
        file_name = os.path.basename(temp_file2.name)
        full_path = temp_file2.name
        stat = os.lstat(full_path)
        info2 = fileinfo.file_info(file_name, full_path, stat)
        q_in.put((1, info2))
        q_in.put(None)
        q_out = Queue.Queue()
        fileinfo.checksum_generator(q_in, q_out)
        self.assertEqual((0, info1), q_out.get_nowait())
        self.assertEqual((1, info2), q_out.get_nowait())
        self.assertIsNone(q_out.get_nowait())
        self.assertTrue(q_out.empty())

if __name__ == '__main__':
    unittest.main()
