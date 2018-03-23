#!/usr/bin/python3

import os
import uuid
import pathlib
import shutil
import sys
import threading
import time
import subprocess
import queue
import glob
import shlex
import json
import sqlite3
import psutil

import nflib

start_epochtime = str(int(time.time()))
data = json.loads(sys.argv[1])

uuid = data['run_uuid']
nf_filename = pathlib.Path(data['nf_filename'])
new_root = pathlib.Path(data['new_root'])
prog_dir = pathlib.Path(data['prog_dir'])
arguments = data['arguments']
input_str = data['input_str']
# --
user = data['user']
sample_group = data['sample_group']
workflow = data['workflow']
context = data['context']

run_dir = new_root / "runs" / uuid
print(run_dir)

os.makedirs(str(run_dir), exist_ok=True)
shutil.copy2(str(prog_dir / nf_filename), str(run_dir))

try:
    shutil.copy2(str(prog_dir / 'nextflow.config'), str(run_dir))
except:
    pass
try:
    shutil.copy2(str(prog_dir / 'nextflow' / 'nextflow.config'), str(run_dir))
except:
    pass

oldpwd = os.getcwd()
os.chdir(str(run_dir))

T = None
pid = None
q = queue.Queue()

def run_nextflow(queue):
    cmd = "nextflow {0} -w {1} -with-trace -with-report -with-timeline -with-dag {2} {3}".format(nf_filename.name, new_root, arguments, input_str)
    print("nextflow cmdline: {0}".format(cmd))
    P = subprocess.Popen(shlex.split(cmd))
    ppid = os.getpid()
    print("python process pid: {0}".format(ppid))
    proc = psutil.Process(ppid)
    while not proc.children():
        print("waiting for nextflow to start...")
        time.sleep(0.1)
    procchild = proc.children()[0]
    print("found child process: {0}".format(str(procchild)))
    pid = procchild.pid
    queue.put(pid)
    queue.put(ppid)
    print("nextflow process pid: {0}".format(pid))
    print("thread waiting for nextflow")
    ret = P.wait()
    print("nextflow process terminated with code {0}".format(ret))

T = threading.Thread(target=run_nextflow, args=(q,))
T.start()

pid = str(q.get())
ppid = str(q.get())

cache_dir = pathlib.Path(run_dir / '.nextflow' / 'cache')
while not cache_dir.is_dir():
    print("Waiting for cache dir to be created...")
    time.sleep(1)

os.chdir(str(new_root))

with open(str(run_dir / '.nextflow' / 'history')) as history_i:
    with open('history', 'a') as history_o:
        history_o.write(history_i.read())

internal_uuid = (run_dir / '.nextflow' / 'cache').iterdir().__next__().name
print("Internal uuid: {0}".format(internal_uuid))

os.makedirs('traces', exist_ok=True)
os.makedirs('pids', exist_ok=True)
os.makedirs('maps', exist_ok=True)

with open(str(pathlib.Path('pids') / "{0}.pid".format(internal_uuid)), 'w') as f:
    f.write(pid)

os.symlink(str(run_dir / 'trace.txt'), str(pathlib.Path('traces') / "{0}.trace".format(internal_uuid)))

#HistoryEntry = namedtuple('HistoryEntry', ['date_time', 'duration', 'code_name', 'status', 'hash', 'uuid', 'command_l

end_epochtime = str(int(time.time()))
hist = nflib.parseHistoryFile(run_dir / '.nextflow' / 'history')
other = (user,
         sample_group,
         workflow,
         context,
         uuid,
         start_epochtime,
         pid,
         ppid,
         end_epochtime)

con = sqlite3.connect("{0}/nfweb.sqlite".format(oldpwd))
s = tuple(list(hist[0])) + other
#print(s)
con.execute("insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", s)
con.commit()

T.join()

os.remove(str(pathlib.Path('pids') / "{0}.pid".format(internal_uuid)))

h = []
for history_i_fn in glob.glob('runs/*/.nextflow/history'):
    with open(history_i_fn) as history_i:
        h.append(history_i.read())
with open("history", 'w') as history_f:
    history_f.write("".join(h))

hist = nflib.parseHistoryFile(run_dir / '.nextflow' / 'history')
con.execute("delete from nfruns where uuid = ?", (internal_uuid,))
s = tuple(list(hist[0])) + other
#print(s)
end_epochtime = str(int(time.time()))
other = (user,
         sample_group,
         workflow,
         context,
         uuid,
         start_epochtime,
         pid,
         ppid,
         end_epochtime)
con.execute("insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", s)
con.commit()
    
os.chdir(str(oldpwd))
print("go.py: done")
