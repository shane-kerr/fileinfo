import argparse
import base64
import collections
#import dbm
#import dbm.ndbm
#import dbm.sqlite3
import io
#import multiprocessing
#import pickle
import sys
#import tempfile
#import threading


#class InodeCache:
#    #def __init__(self, in_mem_limit):
#        #self.lru = collections.OrderedDict()
#        #self.in_mem_limit = in_mem_limit
#    def __init__(self):
#        self.tmp_file = tempfile.NamedTemporaryFile(dir="/var/tmp")
#        self.dbm_store = dbm.ndbm.open(self.tmp_file.name, 'n', 0o600)
#
#    def __getitem__(self, key):
#        #if key in self.lru:
#        #    return self.lru[key]
#        dbm_val = self.dbm_store[str(key)]
#        val = pickle.loads(dbm_val)
#        #self[key] = val
#        return val
#
#    def __contains__(self, key):
#        #return (key in self.lru) or (str(key) in self.dbm_store)
#        return str(key) in self.dbm_store
#
#    def __setitem__(self, key, val):
#        #self.lru[key] = val
#        #self.lru.move_to_end(key)
#        #if len(self.lru) > self.in_mem_limit:
#        #    of_key, of_val = self.lru.popitem(last = False)
#        #    dbm_of_val = pickle.dumps(of_val)
#        #    self.dbm_store[str(of_key)] = dbm_of_val
#        dbm_val = pickle.dumps(val)
#        self.dbm_store[str(key)] = dbm_val


class FileInfoReader:
    def __init__(self, fname):
        self.fname = fname
        self.fp = None
        self.size = None
        self.dir = None
        self.is_fat_fs = None
        #self.inode_lifetimes = None
        #self.inodedb = None
        self.last_file_info = {}

    def start(self):
        self.fp = open(self.fname)
        self.size = self.fp.seek(0, io.SEEK_END)
        self.fp.seek(0, io.SEEK_SET)
        line = self.fp.readline(128)
        if line != '%fileinfo 0.4+n\n':
            return 'Invalid version'
        return None

    def scan_inode(self, output='oneline'):
        #self.cache = tempfile.NamedTemporaryFile()
        #self.inodes = dbm.open(self.cache.name, 'n', 0o600)
        #self.inodes = dbm.ndbm.open(self.cache.name, 'n', 0o600)
        #self.inodes = dbm.sqlite3.open(self.cache.name, 'n', 0o600)
        ## CREATE TABLE Dict (
        ##   key BLOB UNIQUE NOT NULL,
        ##   value BLOB NOT NULL
        ## );
        #self.inodes._execute('CREATE INDEX keyidx ON Dict (key)')
        #self.inodedb = InodeCache(1_900_000)
        #self.inodedb = InodeCache()

        save_fp = self.fp.seek(0, io.SEEK_SET)

        last_inode = None
        inodes_linked = {}
        n = 0
        while (line := self.fp.readline(1024*1024)) != '':
            if line[0] == 'i':
                last_inode = int(line[1:])
        #        #self.inodes.add(int(line[1:]))
        #        #self.inodes[line[1:].strip()] = "0":sh

        #        #self.inodes.put(line[1:].strip(), "")
            elif line[0] == '@':
                inodes_linked[last_inode] = None
            n += 1
            if n >= 65536:
                n = 0
        #        #print(f"\r{self.fname} inode-scan: {self.progress()}%", end='')
                nfound = len(inodes_linked)
                if output == 'oneline':
                    print(f"\r{self.fname} inode-scan: {nfound} links, {self.progress()}%", end='', flush=True, file=sys.stderr)
        ##print(f"\r{' ' * (len(self.fname) + 18)}\r", end='')
        nfound = len(inodes_linked)
        print(f"\r{self.fname} inode-scan: {nfound} links, {self.progress()}%", file=sys.stderr)

        self.fp.seek(save_fp, io.SEEK_SET)
        return inodes_linked

        #line_num = 0
        #last_inode = None
        #self.inode_lifetimes = {}
        #n = 0
        #while (line := self.fp.readline(1024*1024)) != '':
        #    line_num += 1
        #    if line[0] == 'i':
        #        last_inode = int(line[1:])
        #    elif line[0] == '>':
        #        if last_inode in inodes_linked:
        #            self.inode_lifetimes[last_inode] = [line_num, line_num]
        #    elif line[0] == '@':
        #        self.inode_lifetimes[last_inode][1] = line_num
        #    n += 1
        #    if n >= 65536:
        #        n = 0
        #        if output == 'oneline':
        #            print(f"\r{self.fname} inode-scan (phase 2, getting first/last usage for links): {self.progress()}%", end='', flush=True)

        #print(f"\r{self.fname} inode-scan (phase 2, getting first/last usage for links): {self.progress()}%")
        #self.fp.seek(0, io.SEEK_SET)

        #sys.exit(1)
        #return None

    def progress(self):
        pos = self.fp.tell()
        return f'{(pos * 100) / self.size:.1f}'

    def next(self):
        file_info = {}
        while (line := self.fp.readline(1024*1024)) != '':
            cmd, data = line[0], line[1:-1]

            if cmd == '!':
                self.dir = data
                self.is_fat_fs = False
                continue
            if cmd == ':':
                self.dir = data
                self.is_fat_fs = True
                continue

            if cmd == '@':
                #return self.dir, data, self.inodes[file_info["inode"]],
                #return self.dir, data, self.inodedb[file_info["inode"]]
                return self.dir, data, None, file_info["inode"]

            if cmd == '>':
                for info in ('mode', 'links', 'uid', 'gid',
                             'size', 'ctime', 'atime'):
                    if info not in file_info:
                        file_info[info] = self.last_file_info[info]
                if 'mtime' not in file_info:
                    file_info['mtime'] = file_info['ctime']
                if 'flags' not in file_info:
                    file_info['flags'] = 0

                if self.is_fat_fs:
                    file_info['ctime'] &= ~1
                    file_info['atime'] &= ~1
                    file_info['mtime'] &= ~1
                
                # store the value in the inode cache if necessary
                #if file_info["inode"] in self.inodes:
                #    #self.inodes[file_info["inode"]] = file_info
                #    self.inodedb[file_info["inode"]] = file_info

                # save our values
                self.last_file_info = file_info

                return self.dir, data, file_info, None

            if cmd == 'm':
                file_info["mode"] = int(data, 8)
            elif cmd == 'i':
                file_info["inode"] = int(data)
                #file_info["inode"] = data
            elif cmd == 'n':
                file_info["links"] = int(data)
            elif line.startswith('u'):
                file_info["uid"] = int(data)
            elif line.startswith('g'):
                file_info["gid"] = int(data)
            elif line.startswith('s'):
                file_info["size"] = int(data)
            elif line.startswith('C'):
                file_info["ctime"] = data
            elif line.startswith('M'):
                file_info["mtime"] = data
            elif line.startswith('A'):
                file_info["atime"] = data
            elif line.startswith('#'):
                file_info["hash"] = base64.b64decode(data)
            elif line.startswith('r'):
                file_info["dev_id"] = int(data)
            elif line.startswith('f'):
                file_info["flags"] = int(data)

        return None, None, None, None


def file_cmp(fi1, fi2, links1):
    if (fi1[0] < fi2[0]) or (fi1[1] < fi2[1]):
        return 'only in <', [fi1[:2]]
    if (fi1[0] > fi2[0]) or (fi1[1] > fi2[1]):
        return 'only in >', [fi2[:2]]

    info1 = fi1[2]
    info2 = fi2[2]
    if (info1 is None) and (info2 is not None):
        return '< linked, > not linked', [fi1[:2]]
    if (info1 is not None) and (info2 is None):
        return '< not linked, > linked', [fi1[:2]]
         
    mismatches = []
    if info1:
        # XXX: is this needed?
        if info2 is None:
            return '< not linked, > linked', [fi1[:2]]
        for data in ('mode', 'links', 'uid', 'gid',
                     'size', 'mtime', 'flags', 'dev_id'):
            if info1.get(data) != info2.get(data):
                mismatches.append([data, info1.get(data), info2.get(data)])
        inode1 = info1["inode"]
        if (not mismatches) and (inode1 in links1):
        #if inode1 in links1:
            # XXX: what are we doing here?
            links1[inode1] = info2["inode"]
    else:
        # XXX: is this needed?
        if info2:
            return '< linked, > not linked', [fi1[:2]]
        inode1 = fi1[3]
        inode2 = fi2[3]
        if links1[inode1] != inode2:
            # XXX: why is this here?
            #mismatches.append(['inode', inode1, inode2])
            pass

    if mismatches:
        return 'mismatch', [fi1[:2], mismatches]

    return 'okay', []


def diff_fileinfo(f1, f2):
    fir1 = FileInfoReader(f1)
    assert fir1.start() is None
    fir2 = FileInfoReader(f2)
    assert fir2.start() is None
    links1 = fir1.scan_inode()
    
    #t1 = threading.Thread(target=fir1.start)
    #t1 = multiprocessing.Process(target=fir1.start)
    #t2 = threading.Thread(target=fir2.start)
    #t2 = multiprocessing.Process(target=fir2.start)
    #t1.start()
    #t2.start()
    #t1.join()
    #t2.start()
    #t2.join()
    #fir2 = FileInfoReader(f2)
    #assert fir2.start() is None
    #print(f"{f2} ready")
    r1 = fir1.next()
    r2 = fir2.next()
    n = 0
    while (r1[0] is not None) and (r2[0] is not None):
        res, details = file_cmp(r1, r2, links1)
        if res != 'okay':
            print(res, details)
        if res == 'only in <':
            r1 = fir1.next()
            continue
        if res == 'only in >':
            r2 = fir2.next()
            continue
        r1 = fir1.next()
        r2 = fir2.next()

        n += 1
        if n >= 1024:
            n = 0
            print(f"\r{f1}: {fir1.progress()}%   {f2}: {fir2.progress()}%", end='', flush=True, file=sys.stderr)

    while r1[0] is not None:
        print('only in <', r1)
        r1 = fir1.next()

    while r2[0] is not None:
        print('only in >', r2)
        r2 = fir2.next()

    print(f"\r{f1}: 100.0%   {f2}: 100.0%", file=sys.stderr)


def main(argv):
    parser = argparse.ArgumentParser(description='Compare file information.')
    parser.add_argument('fileinfo', nargs=2,
                        help='name of files to read file information from')
    args = parser.parse_args()
    diff_fileinfo(*args.fileinfo)


if __name__ == '__main__':
    main(sys.argv)
