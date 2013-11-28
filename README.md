fileinfo
====

This program outputs meta-information about directories and files that
can be used to detect any changes in these. This is useful when
looking at backups made using file systems that do not checksum file
contents (everything but btrfs in 2013).

Currently the program is missing a way to use the meta-information to
_check_ directories and files, but that is planned.

Usage
----
A usage summary is available via help:

    $ python fileinfo.py --help
    usage: fileinfo.py [-h] [-n NCPUS] [-o OUTFILE] [-p] [-s]
                       [directory [directory ...]]

    Output file information.

    positional arguments:
      directory             where to report file information from (reports 
                            current directory if none specified)
    
    optional arguments:
      -h, --help            show this help message and exit
      -n NCPUS, --ncpus NCPUS
                            number of cores to use (defaults to number of 
                            cores, which is N on this system)
      -o OUTFILE, --outfile OUTFILE
                            file to write to (defaults to STDOUT)
      -p, --progress        output progress as information is recorded
      -s, --summary         output summary information when complete
`

File Format
----
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

There are a few missing fields:

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

Performance
----
There is not much processing going on - mostly the program just reads
information from the file system and outputs it. The exception to this
is calculating the checksum. The checksum calculation is handled with
multiple processes, defaulting to the number of cores on the system.
The optimal number of cores will depend on whether the disks are hard
disks or SSD, the speed of the cores, and so on. If you want maximum
performance, the best approach is to play around with the number of
cores via the "-n" option and seeing what works best on your
environment.

Python Version Compatiability
----
fileinfo.py has been tested with:

    * Python 2.6
    * Python 2.7
    * Python 3.2
    * Python 3.3
    * PyPy 2.0
    * Jython 2.7beta1

Jython is not recommended, due to the limitations described in
doc/Jython.txt.

IronPython is not supported at all, for reasons explained in
doc/IronPython.txt.

