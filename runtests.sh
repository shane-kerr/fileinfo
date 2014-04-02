#! /bin/bash

test_with_version() {
    which $1 > /dev/null
    if [ $? -ne 0 ]; then
        echo SKIPPING TESTS FOR $1
        return
    fi
    echo Testing with $*
    time $* test_fileinfo.py
    if [ $? -ne 0 ]; then
        RETVAL=$?
        echo TESTS FAILED FOR $1
        exit $RETVAL
    fi
}

# CPython 2.x
test_with_version python2.6
test_with_version python2.7

# CPython 3.x
test_with_version python3.2
test_with_version python3.3
test_with_version python3.4

# PyPy 2.x and 3.x
test_with_version pypy
#test_with_version ~/pypy3-2.1-beta1-src/pypy-c

# Jython 2.7 (2.5 version has different try/except syntax, 2.6 does not exist)
test_with_version ~/jython2.7b1/bin/jython

# see doc/IronPython.txt for a description of the limitations of IronPython
#test_with_version mono ~/tmp/IronPython-2.7.4/ipy64.exe

