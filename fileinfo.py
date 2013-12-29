r"""
This program outputs meta-information about directories and files that
can be used to detect any changes in these. This is useful when
looking at backups made using file systems that do not checksum file
contents (everything but btrfs in 2013).

The file format is line-oriented Unicode text. It can be read by a
human, and when compressed is roughly the same size as a binary
format. The basic syntax is that the first character of the line
identifes the contents of the line, and the remainder of the line any
information associated with that.

Files start with a line indicating the version:

    %fileinfo 0.3

A change of directory may be indicated by either a '!' (exclamation
point) or a ':' (colon). An exclamation point indicates a directory on
a Unix-like file system, and a colon indicates a directory on a
FAT-based file system (from MS-DOS or Windows). This distinction is
necessary since FAT file systems are only accurate to within 2
seconds, so checks need to be aware that reported timestamps should
ignore the low bit of reported times:

    !example
    :example

Most information is meta-data about files. For example:

    m100644
    i4196237
    n1
    u1000
    g1000
    s105
    C20131003215722.14093
    A20131003215729.572949
    #GA0M/SJY26NzYANCbFjjEEnnxb73kfx0Icw+jg==
    >hello.c

The file information is:

    m - the file mode ("ls -l" shows -rw-r--r-- in this case)
    i - inode number ("ls -i" outputs this)
    n - count of hard links to the file (output by "ls -l")
    u - user id (uid) of the owner
    g - group id (gid) that the file belongs to
    s - size of the file in bytes
    C - time of last status change
    A - time of last access
    # - SHA224 hash of the file, base64-encoded (regular files only)
    > - the name of the file, possible escaped (see below)

A way to minimize redundant information is by observing that most
files in a directory are owned by the same user, so for example the
owner information is output only once, and then subsequent files are
assumed to have the same owner unless specified. This simple reduction
is not optimal in all cases, but is straightforward and very
effective. This technique is not used for the hash, nor for any of the
fields below.

There are a few missing fields in the example:

    M - time of last modification
    r - device ID
    f - flags

Because the C and M values (ctime and mtime) are often the same, so we
don't bother to output the mtime value if it is identical to the
ctime. The device ID, r, is only meaningful for special files. And the
flags, f, is usually 0, so not output in that case.

Time values are output in ISO 8601 format. Resolution is to
microseconds if Python 2.x is used, or nanoseconds if Python 3.x is
used. Sub-second accuracy is only used when non-zero, and only as much
is available. So we see that only 5 digits are used for ctime here,
and 6 for atime. This has the nice effect of producing shorter output
for file systems that only support second accuracy.

File names may be escaped, if there are unprintable characters
contained (in Python 2.x all non-ASCII characters are considered
unprintable since there is no function to determine which characters
are printable). The escaping rules are:

    * Non-printable 8-bit characters (and backslash) are escaped as \xXX
    * Non-printable 16-bit characters are escaped as \uXXXX
    * Non-printable 32-bit characters are escaped as \UXXXXXXXX

Hash values are only calculated for regular files. Also, if there is
an error calculating the hash value for a file (for example if the
file is not readable by the user running the program) then the hash
value is omitted for that particular file.

Finally, an "inode cache" is used. For files that have already had
information output in the form of an inode, only the inode number and
the name of the file is output - the other details are identical to
the previous time the file was output.
"""

# Experiment 1: output binary rather than text values
# Implementation:
#     Same approach, but use struct.pack() to make a binary output
#     rather than text output. Eliminate newlines, and so on.
# Result:
#     File was 0.68 the size of text file! However, the binary file 
#     compressed with gzip was 0.96 the size of the text file compressed 
#     with gzip, and the binary file compressed with bzip2 was 1.02 the
#     size of the text file compressed with bzip2.
# Decision:
#     Omit binary mode as it complicates the code, is impossible to read
#     without a special decoder, and the compressed version is no smaller.

# Experiment 2: cache inodes and only output inode for hard links
# Implementation:
#     Use a simple dictionary.
# Result:
#     File was 0.99 the size of un-cached version, with the bzip2 
#     compressed version 0.98 the size. Consumes a moderate amount of 
#     memory.
# Decision:
#     Re-test on a directory with lots of hard link. Perhaps make a
#     run-time option, and/or make a more memory efficient structure
#     to track inodes seen.

# Experiment 3: cache ctime/mtime/atime values
# Implementation:
#     Use a simple dictionary mapping times to ctime/mtime/atime of an 
#     inode.
# Result:
#     File was 0.83 the size of the un-cached version, however the 
#     bzip2 compressed version was 0.98 the size of the bzip2 compressed
#     un-cched version.
# Decision:
#     Omit date cache as it complicates the code, makes timestamps 
#     difficult to read, and the compressed version is only marginally 
#     smaller.

# Experiment 4: use external checksum program
# Implementation:
#     Invoke "sha224sum" via subprocess.check_output().
# Result:
#     Output for a sample directory took 26.73 seconds with an external
#     sha224sum program, and 1.16 seconds with the internal hash 
#     library.
# Decision:
#     Stick with internal hash library.

# Experiment 5: multi-core support
# Implementation:
#     Creating the hash values takes a lot of CPU time, so that is
#     reasonable to split out into separate processing. The main task
#     sends files to a set of hashing tasks, who compute the hash and
#     then send it to a serializing task (this insures that the
#     results are always the same no matter how many cores are used or
#     how long each hash generation takes).
#     This work was done using the Python threading module, as well as
#     the Python multiprocessing module, which is very similar.
# Result:
#     multiprocessing yielded the best scaling, although there was a 
#     slight slowdown for the 1-CPU case with multicore code.
# Decision:
#     Use multiprocessing, but special-case 1-CPU to maximize 
#     single-core performance.

# Other considerations:
# * Use of hex or other more compact system for writing numbers was 
#   rejected as it resulted in minimal size reduction, and makes it
#   more difficult for humans ("ls -i" uses decimal, for example).
# * Directories seem to default to st_blksize as the minimum size, so 
#   setting the default of st_size to that instead of the previous
#   entry could result in some savings. However, since directories are
#   clustered together in os.walk() processing, the savings would be
#   minimal, and we would have to track st_blksize for each directory.

import os
import os.path
import sys
import hashlib
import stat
import time
import base64
import argparse
import errno
import signal
import platform

try:
    # Jython doesn't have __builtins__, but we can import __builtin__
    import __builtin__
except ImportError:
    # But of course Python 3 doesn't have the __builtin__ module...
    __builtin__ = __builtins__

try:
    import multiprocessing
    use_threads = False
except ImportError:
    # Jython has no multiprocessing module, so we must use threads
    import Queue
    import threading
    use_threads = True

# TODO: finish docstrings
# TODO: finish tests
# TODO: system-level tests (lettuce?)
# TODO: man page
# TODO: checker program
#       should compare file names in each directory to make sure none added
# TODO: localization?
# TODO: paths relative vs. absolute?
# XXX: file info for non-directories... (on command line)
# TODO: update progress when large files being processed
# TODO: Additional code to shorten time (Am... maybe for 0.4)
# XXX: stat() value change between lstat() and open()
# TODO: recover from errors in multiprocessing units, for example:
#    Traceback (most recent call last):
#      File "app_main.py", line 72, in run_toplevel
#      File "fileinfo.py", line 908, in <module>
#        main()
#      File "fileinfo.py", line 840, in main
#        this_dir = chdir_info(root)
#      File "fileinfo.py", line 412, in __init__
#        if is_fatfs_file(dir_name):
#      File "fileinfo.py", line 390, in is_fatfs_file
#        fcntl.ioctl(fd, FAT_IOCTL_GET_ATTRIBUTES, "\x00")
#    IOError: [Errno 11] Resource temporarily unavailable
# TODO: change name of sub-processes to indicate operation
# TODO: status reports from sub-processes?
# TODO: speed performance on single-core operation
# XXX: error messages while giving status...
# TODO: set onerror in os.walk()
# TODO: errors with lstat() calls
# TODO: output user name as well as number?
# TODO: auto-determine number of cores to run
# TODO: checksum for file itself, maybe also byte & file counts for 
#       contents & file?

# The file information meta-file has a version identifier, which will
# aid when checking meta-file from older versions, that is to say 
# provide backwards compatability. Forwards compatability is not 
# attempted - upgrade your checker.
FILEINFO_VERSION="0.3"

def escape_filename(filename):
    r'''Escape a file name so it can be used in a text file.

    :param filename: a string with the name of a file

    The purpose of this function is to prepare a file name for output
    to the file information text file. Returns a string with the
    escaped name.
    
    The following rules are used, in the order given:

    * The backslash is converted to \x5c
    * Control characters (characters 0 to 31) and their 8-bit
      equivalents are escaped as \xXX
    * If strings have the :py:func:`string.isprintable` method
      (available in Python 3) and the character is printable then it
      is left "as is"
    * 8-bit characters are escaped as \xXX
    * 16-bit characters are escaped as \uXXXX
    * Anything else is escaped as \UXXXXXXXX
    '''
    # XXX: fix the reference to isprintable() above
    escaped_chars = [ ]
    for c in filename:
        n = ord(c)
        if (n < 32) or ((n >= 0x7f) and (n <= 0xa0)) or (c == '\\'):
            escaped_chars.append("\\x%02x" % n)
        elif (n < 0x7f) or (hasattr(c, "isprintable") and c.isprintable()):
            escaped_chars.append(c)
        elif n <= 0xff:
            escaped_chars.append("\\x%02x" % n)
        elif n <= 0xffff:
            escaped_chars.append("\\u%04x" % n)
        else:
            escaped_chars.append("\\U%08x" % n)
    return ''.join(escaped_chars)

def stat_has_time_ns():
    """Determine whether the stat() function provides nanosecond resolution.
    Usually Python 3 can provide nanosecond resolution, and Python 2 not.
    """
    s = os.lstat('.')
    if hasattr(s, 'st_atime_ns') and \
       hasattr(s, 'st_ctime_ns') and \
       hasattr(s, 'st_mtime_ns'):
        return True
    else:
        return False

def file_time(sec, nsec):
    """Return the time as an ISO 8601 formatted string.

    :param sec: epoch time, the number of seconds since 1970-01-01T00:00:00
    :param nsec: nanoseconds past the epoch time

    If there are nanoseconds, these are included with as much precision
    as possible (implemented by removing trailing zeros).
    """
    iso_time = time.strftime("%Y%m%d%H%M%S", time.gmtime(sec))
    if nsec > 0:
        nsec_str = "%09d" % nsec
        return iso_time + "." + nsec_str.rstrip("0")
    else:
        return iso_time

def nsec_ftime_value(f):
    """Extract nanoseconds from floating-point file time

    :param f: floating-point file time, as returned by stat()

    This function is useful if we don't have nanosecond attributes, so
    we can use the floating-point values instead. Sadly IEEE 754
    doubles only have 16 decimal digits, which gives us only 6 digits
    of time resolution after the decimal point.

    The following blog entry explains in more detail:

    http://ciaranm.wordpress.com/2009/11/15/this-week-in-python-stupidity-os-stat-os-utime-and-sub-second-timestamps/
    """
    # Remove the whole seconds from the floating point time, leaving only
    # the fractional part:
    #    1377602503.85704803466796875 -> 0.85704803466796875
    sub_sec = f - int(f)
    # Next get 6 digits of the fractional time by using multiplication 
    # to move them to the left of the decimal point, then rounding to 
    # remove any digits after the decimal point:
    #    0.85704803466796875 -> 857048.0
    usec = round(sub_sec * 1000000)
    # Finally convert the value into nanoseconds by multiplication.
    # Since we got 6 digits, that means that we have microseconds and 
    # need to multiply by 1000 to get the equivalent number of nanoseconds:
    #    857048.0 -> 857048000
    return int(usec * 1000)

def file_time_details(st):
    """Returns ISO 8601-formatted versions of atime, ctime, and mtime

    :param st: information from a stat call

    If nanosecond resolution is available we use that, otherwise the
    floating point resolution (microseconds) is used.
    """
    if hasattr(st, 'st_atime_ns'):
        atime = file_time(st.st_atime, st.st_atime_ns % 1000000000)
    else:
        atime = file_time(st.st_atime, nsec_ftime_value(st.st_atime))
    if hasattr(st, 'st_ctime_ns'):
        ctime = file_time(st.st_ctime, st.st_ctime_ns % 1000000000)
    else:
        ctime = file_time(st.st_ctime, nsec_ftime_value(st.st_ctime))
    if hasattr(st, 'st_mtime_ns'):
        mtime = file_time(st.st_mtime, st.st_mtime_ns % 1000000000)
    else:
        mtime = file_time(st.st_mtime, nsec_ftime_value(st.st_mtime))
    return (atime, ctime, mtime)

# FAT file systems only have accuracy down to 2 seconds, but
# unfortunately Linux reports timestamps down to 1 second, which is
# misleading, since when a FAT file system is unmounted and re-mounted
# the timestamps can be returned as if they had changed.
#
# For example, if a file is modified at:
#    2013-09-20 21:10:01
# It will return that value via stat(), however after a re-mount the
# modification date will be reported as:
#    2013-09-20 21:10:00
#
# To work around this, we want to detect when we have a FAT file
# system.


if platform.system() == 'Linux':
    # The following function is Linux-specific, on BSD variants we can
    # possibly use os.statvfs() where the underlying statfs() call returns
    # the type of the file system. Otherwise we'll have to use ctypes
    # or the like to get to the elements of the underlying structures.

    # Note that this also fails when using Jython, as fcntl is not 
    # supported and possibly never will be. Details here:
    # http://bugs.jython.org/issue1074

    import fcntl
    
    # This is defined in <linux/msdos_fs.h>
    #
    # We express it as a negative number, because otherwise pypy 
    # considers it a long integer and raises an exception when using
    # it as an argument to fcntl.ioctl().
    FAT_IOCTL_GET_ATTRIBUTES = -2147192304   # 0x80047210

    def is_fatfs_file(name):
        """Determine if the given file is on a FAT file system (Linux-only)

        :param name: the name of a file

        The approach we use is to use an ioctl() which returns FAT file 
        attributes. This only works on FAT file systems, and raises an 
        exception on other file systems - this should be ENOTTY according
        to the ioctl() man page, but at least one file system (NTFS-3G)
        returns ENOSYS.
 
        The use of the ioctl() is based on this code:
        http://stackoverflow.com/questions/15895525/get-fat32-attributes-with-python
        """
        # XXX; fix reference to ioctl() man page above
        fd = os.open(name, os.O_RDONLY)
        try:
            fcntl.ioctl(fd, FAT_IOCTL_GET_ATTRIBUTES, "\x00")
        except IOError as e:
            if e.errno in (errno.ENOTTY, errno.ENOSYS):
                return False
            else:
                raise
        finally:
            os.close(fd)
        return True
else:
    # hm.. possibly look for side effects, like allowed characters in file
    # names, case-insensitivity, and the like?
    def is_fatfs_file(name):
        """Determine if the given file is on a FAT file system

        :param name: the name of a file

        If we don't have any way to determine if a file system is FAT, we
        just assume that it is not and hope for the best.
        """
        return False
    
"""
To support multiple cores, we have a number of worker threads handling
hash generation.

We have three types of thread:

* The main thread finds and stats files
* Worker threads compute the hash of regular files
* A serializer thread outputs information in the correct order

We need the serializer thread because directories and files that are
not regular files (symlinks, FIFOs, and the like) are ready for output
immediately but other files take time beause the hash needs to be
calculated. Even if this were not the case, hash generation takes a
variable amount of time depending on file size. Finally, multicore
operations are inherently unpredictable since we don't know what else
is going on with the system. So we collect all information into the
serializer thread and insure output occurs in a consistent order.

There are 3 types of information that we may want to output:

1. A new directory that we have changed into
2. A file who's inode we have already seen (so just the inode number)
3. A file we have not yet output information for

In the last case we want to calculate a hash if it is a normal file.

The resulting algorithm is this:

* main thread: changes to a directory and sends that information
   to the serializer via a queue
* main thread: gets a file list
* main thread: for each file, stat it. if it is a regular file, send 
   it to a worker thread, otherwise send it to the serializer
* worker thread: get a file, calculate a hash, send to the serializer
* serializer: output information in order
"""

class chdir_info:
    """chdir_info is used to signal a new directory for reporting 
    file information, any metadata output after this originates from 
    the directory specified"""
    def __init__(self, dir_name):
        """initialize the directory name

        :param dir_name: the name of the directory

        The constructor determines whether or not the specified
        directory is a FAT-style directory.
        """
        self.dir_name = dir_name
        if is_fatfs_file(dir_name):
            self.cmd = ':'
        else:
            self.cmd = '!'
    def output(self, out, err, prev_stat):
        """output information about the directory

        :param out: a file-like object for normal output
        :param err: a file-like object for errors (NOT USED)
        :param prev_stat: the last stat object output

        For a directory, all that we output is the appropriate command
        (normally an exclamation point, '!', but a colon, ':', if the
        directory is a FAT-style directory).

        Since changing directory outputs no file information, we
        return the prev_stat variable for use in future calls.
        """
        out.write(self.cmd + 
                  escape_filename(os.path.normpath(self.dir_name)) + "\n")
        return prev_stat

class cached_info:
    """cached_info is a special class used when we want to output 
    metadata for an inode that we have earlier output"""
    def __init__(self, file_name, stat):
        """initialize the cached information

        :param file_name: the name of the file
        :param stat: the value returned by os.lstat() for the file
        """
        self.file_name = file_name
        self.stat = stat
    def output(self, out, err, prev_stat):
        """output information about a cached inode

        :param out: a file-like object for normal output
        :param err: a file-like object for errors (NOT USED)
        :param prev_stat: the last stat object output (NOT USED)
        """
        out.write("i%d\n" % self.stat.st_ino)
        out.write(">" + escape_filename(self.file_name) + "\n")
        return self.stat

class file_info:
    """file_info is the main class that contains metadata about files
    and outputs information about them. The initalizer and a couple of
    support functions set values. The output() function has the main
    logic which implements the efficient metadata output for the
    program."""
    def __init__(self, file_name, full_path, stat):
        """initialize the file information

        :param file_name: the name of the file
        :param full_path: the full path to the file (used for hashing)
        :param stat: the value returned by os.lstat() for the file

        The hash and any hash error are both set to None.
        """
        self.file_name = file_name
        self.full_path = full_path
        self.stat = stat
        self.encoded_hash = None
        self.hashing_error = None
    def set_hash(self, encoded_hash):
        """set the hash for the file

        :param encoded_hash: a base64 encoded hash value to be output"""
        self.encoded_hash = encoded_hash
    def set_hashing_error(self, exception):
        """set the hashing error

        :param exception: exception causing hashing error """
        self.hashing_error = exception
    def output(self, out, err, prev_stat):
        """output information about the file

        :param out: a file-like object for normal output
        :param err: a file-like object for errors (NOT USED)
        :param prev_stat: the last stat object output

        This function outputs information about the file. It is heavily 
        dependent on the previous file information output, since in 
        order to minimize the data output repeated metadata is omitted.
        """
        if self.hashing_error:
            if hasattr(self.hashing_error, 'errno') and \
               hasattr(self.hashing_error, 'strerror'):
                err.write("Error with '" + self.file_name + "': [" + 
                          errno.errorcode[self.hashing_error.errno] + "] " +
                          self.hashing_error.strerror + "\n")
            else:
                err.write("Error with '" + self.file_name + "': " + 
                          str(self.hashing_error) + "\n")

        # most metadata is output if it is different from that
        # of the previous file... most of these are identical for 
        # large groups of files
        if (prev_stat is None) or (self.stat.st_mode != prev_stat.st_mode):
            out.write("m%o\n" % self.stat.st_mode)
        if (prev_stat is None) or (self.stat.st_ino != prev_stat.st_ino):
            out.write("i%d\n" % self.stat.st_ino)
        if (prev_stat is None) or (self.stat.st_nlink != prev_stat.st_nlink):
            out.write("n%d\n" % self.stat.st_nlink)
        if (prev_stat is None) or (self.stat.st_uid != prev_stat.st_uid):
            out.write("u%d\n" % self.stat.st_uid)
        if (prev_stat is None) or (self.stat.st_gid != prev_stat.st_gid):
            out.write("g%d\n" % self.stat.st_gid)
        if (prev_stat is None) or (self.stat.st_size != prev_stat.st_size):
            out.write("s%d\n" % self.stat.st_size)
            
        # XXX: hm... inefficient to convert all the time...
        (this_atime, this_ctime, this_mtime) = file_time_details(self.stat)
        if prev_stat is None:
            (prev_atime, prev_ctime, prev_mtime) = ('', '', '')
        else:
            (prev_atime, prev_ctime, prev_mtime) = file_time_details(prev_stat)
        # XXX: these string comparisons are inefficient?
        # Note: concatenation vs. string substitution performance
        #     Python 2: 0.6 vs 0.7 seconds
        #     Python 3: 1.3 vs 0.9 seconds
        #     pypy:     2.4 vs. 31 seconds (10x more than CPython)
        #     pypy-3:   0.7 vs 0.7 seconds
        if this_ctime != prev_ctime:
            out.write("C" + this_ctime + "\n")
        # Very often the mtime is identical to the ctime.
        # So for mtime we compare with the ctime of *this*
        # file, rather than the mtime of the previous file.
        # XXX: don't need prev_mtime at all!
        if this_ctime != this_mtime:
            out.write("M" + this_mtime + "\n")
        if this_atime != prev_atime:
            out.write("A" + this_atime + "\n")

        # these values are rarely used, so don't bother to minimize them,
        # rather simply don't output them at all if they are 0
        if getattr(self.stat, "st_rdev", 0):
            out.write("r%d\n" % self.stat.st_rdev)
        if getattr(self.stat, "st_flags", 0):
            out.write("f%d\n" % self.stat.st_flags)

        # only regular files have a hash
        if self.encoded_hash is not None:
            out.write("#" + self.encoded_hash + "\n")

        # finally, write out the file name itself
        out.write(">" + escape_filename(self.file_name) + "\n")
        return self.stat

def serializer(q_serializer, num_checksum, outfile):
    finished_checksum_count = 0
    next_number = 0
    result_buffer = { }

    last_stat = None
    while True:
        info = q_serializer.get()

        # When a checksum generator finishes, it passes None on 
        # to the serializer.
        # When they are all done, we can exit.
        if info is None:
            finished_checksum_count = finished_checksum_count + 1
            if finished_checksum_count < num_checksum:
                # waiting on some more checksums...
                continue
            # done processing
            break

        # get the passed information
        (number, result) = info

        # put passed information into our buffer
        result_buffer[number] = result

        # clear out results that have arrived
        while next_number in result_buffer:
            # pull the information out of the buffer
            result = result_buffer[next_number]
            del result_buffer[next_number]
            last_stat = result.output(outfile, sys.stderr, last_stat)
            next_number = next_number + 1

    # we need to explicitly flush before exit due to multiprocessing usage
    outfile.flush()

def get_checksum(chksum_file):
    try:
        h = hashlib.sha224()
        # open with O_NOATIME so calculating checksum doesn't
        # modify the file metadata
        try:
            noatime = getattr(os, 'O_NOATIME', 0)
            fd = os.open(chksum_file.full_path, os.O_RDONLY | noatime)
        except OSError as e:
            # some file system types (like FAT) raise permission
            # error if we try to open a file with O_NOATIME, so catch
            # that and try again without that flag
            if e.errno != errno.EPERM: raise
            fd = os.open(chksum_file.full_path, os.O_RDONLY)
        f = os.fdopen(fd, 'rb')
        while True:
            s = f.read(getattr(chksum_file.stat, 'st_blksize', 8192))
            if len(s) == 0: break
            h.update(s)
        f.close()
        chksum_file.set_hash(base64.b64encode(h.digest()).decode())
    except Exception as e:
        chksum_file.set_hashing_error(e)
    return chksum_file
            
def checksum_generator(q_in, q_out):
    while True:
        info = q_in.get()
        if info is None:
            q_out.put(None)
            return
        (number, chksum_file) = info
        q_out.put((number, get_checksum(chksum_file)))

def output_file_info(dir_name, file_name, outfile, inode_cache,
                     number, q_checksum, q_serializer,
                     ncpus, prev_stat):
    full_path = os.path.normpath(os.path.join(dir_name, file_name))
    this_stat = os.lstat(full_path)

    # Output the meta-data of the file, as returned by lstat().
    # 
    # We omit st_dev, st_blocks, and st_blksize as these are determined
    # by the file system, and are not really useful for our purposes.

    if this_stat.st_ino in inode_cache:
        # if we have previously seen this inode, the rest of the 
        # meta-data has already been output, so all we need to record
        # is the inode number
        info = cached_info(file_name, this_stat)
        if ncpus > 1:
            q_serializer.put((number, info))
        else:
            info.output(outfile, sys.stderr, prev_stat)
    else:
        info = file_info(file_name, full_path, this_stat)
        if ncpus > 1:
            if stat.S_ISREG(this_stat.st_mode):
                # for regular files, we will calculate a hash of the file
                q_checksum.put((number, info))
            else:
                # otherwise we just want to output the meta-data
                q_serializer.put((number, info))
        else:
            if stat.S_ISREG(this_stat.st_mode):
                # for regular files, we will calculate a hash of the file
                info = get_checksum(info)
            info.output(outfile, sys.stderr, prev_stat)
            
        # record the fact that we have seen this inode
        inode_cache[this_stat.st_ino] = True
    return this_stat

def human_time(seconds):
    sub_seconds = seconds - int(seconds)
    seconds = int(seconds)

    days = seconds // (24*60*60)
    seconds = seconds % (24*60*60)
    hours = seconds // (60*60)
    seconds = seconds % (60*60)
    minutes = seconds // 60
    seconds = (seconds % 60) + sub_seconds

    if days > 0:
        return "%dd %02d:%02d:%05.2f" % (days, hours, minutes, seconds)
    elif hours > 0:
        return "%d:%02d:%05.2f" % (hours, minutes, seconds)
    elif minutes > 0:
        return "%d:%05.2f" % (minutes, seconds)
    else:
        return "%.2f" % seconds

def human_bytes(b):
    # calculate base 2 values
    # http://en.wikipedia.org/wiki/Binary_prefix
    if b >= 1024*1024*1024*1024*1024:
        b2 = "%.1f PiB" % (b / (1024 * 1024 * 1024 * 1024 * 1024))
    elif b >= 1024*1024*1024*1024:
        b2 = "%.1f TiB" % (b / (1024 * 1024 * 1024 * 1024))
    elif b >= 1024*1024*1024:
        b2 = "%.1f GiB" % (b / (1024 * 1024 * 1024))
    elif b >= 1024*1024:
        b2 = "%.1f MiB" % (b / (1024 * 1024))
    elif b >= 1024:
        b2 = "%.1f KiB" % (b / 1024)
    else:
        b2 = "%d B"
    # calcluate base 10 values
    # http://en.wikipedia.org/wiki/SI_prefix
    if b >= 1000000000000000:
        b10 = "%.1f PB" % (b / 1000000000000000)
    elif b >= 1000000000000:
        b10 = "%.1f TB" % (b / 1000000000000)
    elif b >= 1000000000:
        b10 = "%.1f GB" % (b / 1000000000)
    elif b >= 1000000:
        b10 = "%.1f MB" % (b / 1000000)
    elif b >= 1000:
        b10 = "%.1f KB" % (b / 1000)
    else:
        b10 = "%d B"
    return "%s / %s" % (b2, b10)

def pl_dir(n):
    if n == 1:
        return "directory"
    else:
        return "directories"

def pl_file(n):
    if n == 1:
        return "file"
    else:
        return "files"

class record_output_size:
    def __init__(self, f):
        self.f = f
        self.size = 0
    def write(self, data):
        self.f.write(data)
        self.size += len(data)
    def flush(self):
        self.f.flush()

class progress_output:
    def __init__(self, num_dir, num_file, progress_interval, start_time=None):
        self.total_dir_count = num_dir
        self.total_file_count = num_file
        self.total_count = num_dir + num_file
        self.dir_count = 0
        self.file_count = 0
        self.progress_interval = progress_interval
        if start_time is None:
            self.start_time = time.time()
        self.last_time = self.start_time
    def _status(self, current_time):
        run_time = current_time - self.start_time
        if (self.total_count != 0) and (run_time > 0):
            progress = " (%.1f%% done, %.1f/second)" % (
                (self.file_count * 100) / self.total_count,
                (self.file_count / run_time))
        else:
            progress = ""
        sys.stderr.write("\r%d %s from %d %s in %s%s" %
            (self.file_count, pl_file(self.file_count), 
            self.dir_count, pl_dir(self.dir_count),
            human_time(run_time), progress))
    def update(self, dir_inc, file_inc, current_time=None):
        self.dir_count = self.dir_count + dir_inc
        self.file_count = self.file_count + file_inc
        if current_time is None:
            now = time.time()
        else:
            now = current_time
        if now - self.last_time >= self.progress_interval:
            self.last_time = now
            self._status(now)
    def complete(self, current_time=None):
        if current_time is None:
            now = time.time()
        else:
            now = current_time
        self._status(now)
        sys.stderr.write("\n")

def make_type_unicode(s):
    """Convert the passed argument into a unicode type.

    :param s: an object to convert

    On Python 2, there is a separate unicode type, so we need to
    convert strings to that type.

    On Python 3, strings _are_ unicode, and there is no "unicode"
    type, so we can safely return the object changed.
    """
    if hasattr(__builtin__, 'unicode'):
        return unicode(s)
    else:
        return s

def main():
    begin_time = time.time()

    # disable Python conversion of SIGINT to KeyboardInterrupt
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if use_threads:
        ncpus = 1
    else:
        ncpus = multiprocessing.cpu_count()

    parser = argparse.ArgumentParser(description='Output file information.')
    # XXX: make sure it is positive
    parser.add_argument('-n', '--ncpus', type=int,
                        help='number of cores to use (defaults to number of cores, which is %d on this system)' % ncpus)
    parser.add_argument('-o', '--outfile', type=str,
                        help='file to write to (defaults to STDOUT)')
    parser.add_argument('-p', '--progress', action="store_true",
                        help='output progress as information is recorded')
    parser.add_argument('-s', '--summary', action="store_true",
                        help='output summary information when complete')
    parser.add_argument('directory', nargs="*",
                        help='where to report file information from (reports current directory if none specified)')
    args = parser.parse_args()

    # XXX: check for ncpus of 0?
    if args.ncpus:
        ncpus = args.ncpus

    if args.outfile:
        outfile = open(args.outfile, 'w')
    else:
        outfile = sys.stdout

    if args.summary:
        outfile = record_output_size(outfile)

    if stat_has_time_ns():
        outfile.write('%%fileinfo %s+n\n' % FILEINFO_VERSION)
    else:
        outfile.write('%%fileinfo %s\n' % FILEINFO_VERSION)
    outfile.flush()

    if args.directory:
        fileinfo_dirs = args.directory
    else:
        fileinfo_dirs = [ '.' ]

    if args.progress:
        total_dirs = 0
        total_files = 0
        sys.stderr.write("Collecting file counts...")
        for fileinfo_dir in fileinfo_dirs:
            for root, dirs, files in os.walk(fileinfo_dir):
                for name in dirs:
                    total_dirs = total_dirs + 1
                for name in files:
                    total_files = total_files + 1
                sys.stderr.write("\rCollecting file counts... %d %s in %d %s" %
                    (total_files, pl_file(total_files), 
                     total_dirs, pl_dir(total_dirs)))
        sys.stderr.write("\n")
        progress = progress_output(total_dirs, total_files, 0.1)

    # create processing units
    if ncpus == 1:
        q_checksum = None
        q_serializer = None
    elif use_threads:
        # XXX: how big should this queue be?
        q_checksum = Queue.Queue(ncpus * 4)
        q_serializer = Queue.Queue()
        serializer_task = threading.Thread(target=serializer, 
                                           args=(q_serializer, ncpus, outfile))
        serializer_task.start()
        for n in range(ncpus):
            threading.Thread(target=checksum_generator,
                                    args=(q_checksum, q_serializer)).start()
    else:
        # XXX: how big should this queue be?
        q_checksum = multiprocessing.Queue(ncpus * 4)
        q_serializer = multiprocessing.Queue()
        serializer_task = multiprocessing.Process(target=serializer, 
                                       args=(q_serializer, ncpus, outfile))
        serializer_task.start()
        for n in range(ncpus):
            multiprocessing.Process(target=checksum_generator,
                                    args=(q_checksum, q_serializer)).start()
    prev_stat = None

    inode_cache = { }
    total_dirs = 0
    total_files = 0
    total_bytes_read = 0
    number = 0
    for fileinfo_dir in fileinfo_dirs:
        # In Python 2, if we invoke os.walk() with a Unicode string
        # we'll get Unicode file names, so we need to insure that 
        # our directory names are Unicode.
        # Python 3 of course always returns Unicode names.
        fileinfo_dir = make_type_unicode(fileinfo_dir)

        for root, dirs, files in os.walk(fileinfo_dir):
            this_dir = chdir_info(root)
            if ncpus > 1:
                q_serializer.put((number, this_dir))
            else:
                this_dir.output(outfile, sys.stderr, prev_stat)
                
            number = number + 1
            if args.progress:
                progress.update(1, 0)
            # do dirs first then files to give us some pipelining...
            # might be nice to have some sort algorithm that outputs
            # as it goes... so the remaining processing can start
            # while the sort completes... hm...
            dirs.sort()
            for name in dirs:
                prev_stat  = output_file_info(root, name, outfile, inode_cache, 
                                              number, q_checksum, q_serializer,
                                              ncpus, prev_stat)
                number = number + 1
                if args.progress:
                    progress.update(0, 1)
            files.sort()
            for name in files:
                prev_stat  = output_file_info(root, name, outfile, inode_cache, 
                                              number, q_checksum, q_serializer,
                                              ncpus, prev_stat)
                number = number + 1
                if args.progress:
                    progress.update(0, 1)
            total_dirs = total_dirs + len(dirs)
            total_files = total_files + len(files)
            # XXX: gather total bytes
#            if stat.S_ISREG(s.st_mode):
#                total_bytes_read = total_bytes_read + s.st_size

    # finish processing and wait for completion
    if ncpus > 1:
        for n in range(ncpus):
            q_checksum.put(None)
        serializer_task.join()

    if args.progress:
        progress.complete()

    if args.summary:
        sys.stderr.write("Number of directories: %8d\n" % total_dirs)
        sys.stderr.write("Number of files:       %8d\n" % total_files)
        # XXX: gather total bytes
#        sys.stderr.write("  Total size:   %15d (%s)\n" % 
#                         (total_bytes_read, human_bytes(total_bytes_read)))
        total_run_time = time.time() - begin_time
        sys.stderr.write("Total run time: %15s\n" % human_time(total_run_time))
        if total_run_time > 0:
            sys.stderr.write("  Directories / second:  %8.1f\n" % 
                             (total_dirs / total_run_time))
            sys.stderr.write("  Files / second:        %8.1f\n" % 
                             (total_files / total_run_time))
        else:
            sys.stderr.write("  Directories / second:       -.-\n" % 
                             (total_dirs / total_run_time))
            sys.stderr.write("  Files / second:             -.-\n" % 
                             (total_files / total_run_time))
            
        # XXX division by 0
#        sys.stderr.write("Size of output:        %8d (%.1f bytes/file)\n" %
#                         (outfile.size, outfile.size / total_files))

if __name__ == "__main__":
    main()
    