#!/usr/bin/python3

#
# This program is run by nfweb.py. It in turn runs nextflow.
# The purpose of this indirection is to allow the it to detach
# from the web gui so that it can be restarted without existing
# runs being terminated.
#

#
# From the working directory, it creates runs/uuid and launches
# nextflow in that directory. Then it waits until nextflow creates
# a file which contains the nextflow uuid that nextflow uses
# to reference the run.
#
# Some symlinks are created to help access data more easily.
#
# The web gui uses an sqlite database (table nfruns) to keep
# track of runs
#

import os
import uuid
import pathlib
import shutil
import sys
import threading
import time
import subprocess
import queue
import shlex
import json
import sqlite3
import psutil

import nflib

# Seconds since 1/1/1970
# https://en.wikipedia.org/wiki/Unix_time
start_epochtime = str(int(time.time()))

# Data to from nfweb.py is passed in here as json
data = json.loads(sys.argv[1])

# Rebind the data
uuid = data['run_uuid']
nf_filename = pathlib.Path(data['nf_filename'])
root_dir = pathlib.Path(data['root_dir'])
prog_dir = pathlib.Path(data['prog_dir'])
arguments = data['arguments']
input_str = data['input_str']
output_arg = data['output_arg']
output_dir = pathlib.Path(data['output_dir'])
user = data['user']
sample_group = data['sample_group']
workflow = data['workflow']
context = data['context']
domain = data['ldap_domain']
output_name = data['output_name']

# Create the run dir
run_dir = root_dir / "runs" / uuid
print(run_dir)

os.makedirs(str(run_dir), exist_ok=True)
#os.makedirs(str(output_dir), exist_ok=True)

# Cache the current directory and then change into the run directory.
oldpwd = pathlib.Path.cwd()
os.chdir(str(run_dir))

internal_uuid = None

def exit_nicely():
    end_epochtime = str(int(time.time()))
    other = (user, sample_group, workflow, context, str(root_dir), output_arg, str(output_dir),
             uuid, start_epochtime, pid, ppid, end_epochtime, output_name, str(data))
    if not internal_uuid:
        # we don't have an internal_uuid, which means there's no history file
        nice_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(start_epochtime)))
        hist = [nice_time, '-', '-', 'FAIL', '-', uuid, '-']
        s = tuple(list(hist)) + other
        nflib.insertRun(s, uuid, oldpwd)
    else:
        hist = nflib.parseHistoryFile(run_dir / '.nextflow' / 'history')
        hist = list(hist[0])
        if nf_returncode != "0":
            hist[3] = "ERR"
        s = tuple(hist) + other
        nflib.reinsertRun(s, uuid, internal_uuid, oldpwd)
    print("exit_nicely(): exiting prematurely but nicely")
    exit(-126)

T = None
pid = None
q = queue.Queue()

# This functions runs nextflow, returns the nxtflow pid to the main thread and wait until nextflow finishes
def run_nextflow(queue):
    cmd = "nextflow {0}/{1} -w {2}/SCRATCH -with-trace -with-report -with-timeline -with-dag {3} {4} {5} {6}".format(prog_dir, nf_filename.name, root_dir, arguments, input_str, output_arg, output_dir)
    print("nextflow cmdline: {0}".format(cmd))
    P = subprocess.Popen(shlex.split(cmd))
    ppid = os.getpid()
    print("python process pid: {0}".format(ppid))
    proc = psutil.Process(ppid)

    # wait until nextflow starts 
    while not proc.children():
        print("waiting for nextflow to start...")
        time.sleep(0.1)

    procchild = proc.children()[0]
    print("found child process: {0}".format(str(procchild)))

    # never happened - not needed?
    if not procchild.name() == 'nextflow':
        print("Excuse me?")
        exit_nicely()
    pid = procchild.pid
    queue.put(pid)
    queue.put(ppid)
    print("nextflow process pid: {0}".format(pid))
    print("thread waiting for nextflow")
    ret = P.wait()
    print("nextflow process terminated with code {0}".format(ret))
    queue.put(ret)

T = threading.Thread(target=run_nextflow, args=(q,))
T.start()

# continue once nextflow is started and we have the pids
pid = str(q.get())
ppid = str(q.get())

def wait_for_cache_dir():
    cache_dir = pathlib.Path(run_dir / '.nextflow' / 'cache')
    print("cache dir = {}".format(str(cache_dir)))

    # wait until nextflow creates the cache dir
    tries = 180
    while not cache_dir.is_dir():
        print("Waiting for cache dir to be created...")
        time.sleep(1)
        tries = tries - 1
        if tries <= 0:
            # Give up after 10 tries
            print("Error: Time out on cache dir")
            return False
    return True

if not wait_for_cache_dir():
    exit_nicely()

# change into the working directory
os.chdir(str(root_dir))

# get the nextflow run uuid. This is different from the nfweb uuid because we need that
# before nextflow starts
internal_uuid = (run_dir / '.nextflow' / 'cache').iterdir().__next__().name # get the first file in directory
print("Internal uuid: {0}".format(internal_uuid))

os.makedirs('traces', exist_ok=True)
os.makedirs('pids', exist_ok=True)
os.makedirs('maps', exist_ok=True)

# write the nextflow run pid into pids/uuid.pid
with open(str(pathlib.Path('pids') / "{0}.pid".format(internal_uuid)), 'w') as f:
    f.write(pid)

# link the run dir (runs/nfweb_uuid) to the internal uuid (maps/internal_uuid) so we can access the run directory
# by referencing the internal uuid
os.symlink(str(run_dir), str(root_dir / 'maps' / internal_uuid))
# link the trace
os.symlink(str(run_dir / 'trace.txt'), str(pathlib.Path('traces') / "{0}.trace".format(internal_uuid)))

# sqlite nfruns table columns reference
#  1 date_time
#  2 duration
#  3 code_name
#  4 status
#  5 hash
#  6 uuid
#  7 command_line
#  8 user
#  9 sample_group
# 10 workflow
# 11 context
# 12 root_dir
# 13 output_arg
# 14 output_dir
# 15 4run_uuid primary key not null
# 16 start_epochtime
# 17 pid
# 18 ppid
# 19 end_epochtime
# 20 output_name
# 21 data_json

end_epochtime = str(int(time.time()))
hist = nflib.parseHistoryFile(run_dir / '.nextflow' / 'history')
other = (user,
         sample_group,
         workflow,
         context,
         str(root_dir),
         output_arg,
         str(output_dir),
         uuid,
         start_epochtime,
         pid,
         ppid,
         end_epochtime,
         output_name,
         str(data))

# add the run to the sqlite database
s = tuple(list(hist[0])) + other
nflib.insertRun(s, uuid, oldpwd)

# wait for nextflow to finish
T.join()
nf_returncode = str(q.get())

# remove pid file
os.remove(str(pathlib.Path('pids') / "{0}.pid".format(internal_uuid)))

# update sqlite database with the end results
hist = nflib.parseHistoryFile(run_dir / '.nextflow' / 'history')
hist = list(hist[0])
if nf_returncode != "0":
    hist[3] = "ERR"
other = (user,
         sample_group,
         workflow,
         context,
         str(root_dir),
         output_arg,
         str(output_dir),
         uuid,
         start_epochtime,
         pid,
         ppid,
         end_epochtime,
         output_name,
         str(data))
s = tuple(hist) + other
end_epochtime = str(int(time.time()))
nflib.reinsertRun(s, uuid, internal_uuid, oldpwd)

# go back to the old directory
# not needed?
os.chdir(str(oldpwd))
print("go.py: done")
