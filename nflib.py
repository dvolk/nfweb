import csv
import yaml
from collections import namedtuple
import pathlib
import typing
import glob
import config
import sqlite3
import pathlib
import time

HistoryEntry = namedtuple('HistoryEntry', ['date_time', 'duration', 'code_name', 'status', 'hash', 'uuid', 'command_line'])
# The trace file fields are vary depending on run parameters
TraceEntry = typing.Dict[str, str]

def parseHistoryFile(nf_history_fp: pathlib.Path) -> typing.List[HistoryEntry]:
    history_nt = list()
    if not nf_history_fp.is_file():
        print("history file {} does not exist".format(nf_history_fp))
        return []

    with open(str(nf_history_fp)) as history_file:
        history_tsv = csv.reader(history_file, delimiter='\t')
        for row in history_tsv:
            if len(row) == 7:
                history_nt.append(HistoryEntry(*row))

    return history_nt

def parseTraceFile(nf_trace_fp: pathlib.Path) -> typing.List[TraceEntry]:
    traces = list()
    if not nf_trace_fp.is_file():
        print("trace file {} does not exist".format(nf_trace_fp))
        return []

    with open(str(nf_trace_fp)) as trace_file:
        reader = csv.DictReader(trace_file, delimiter='\t')
        for row in reader:
            traces.append(row)

    return traces

def getDBConn(pwd : pathlib.Path = pathlib.Path.cwd()):
    # nfweb.sqlite nfruns table is used for tracking nextflow runs
    pwd = pwd / 'nfweb.sqlite'
    con = sqlite3.connect(str(pwd) ,check_same_thread=False)
    con.execute("CREATE TABLE if not exists nfruns (date_time, duration, code_name, status, hash, uuid, command_line, user, sample_group, workflow, context, root_dir, output_dir, run_uuid primary key not null, start_epochtime, pid, ppid, end_epochtime);")
    con.commit()
    return con

def closeDBConn(con: sqlite3.Cursor):
    con.close()

def getStatus():
    # the root page lists the current running runs and the last 5 successful and failed runs
    con = getDBConn()
    running = recent = failed = list()
    try:
        running = con.execute('select * from nfruns where status = "-" order by "start_epochtime" desc').fetchall()
        recent = con.execute('select * from nfruns where status = "OK" order by "start_epochtime" desc limit 5').fetchall()
        failed = con.execute('select * from nfruns where status = "ERR" order by "start_epochtime" desc limit 5').fetchall()
    except:
        print("Error accessing DB")

    closeDBConn(con)
    return (running, recent, failed)

def getWorkflow(flow_name: str):
    con = getDBConn()
    data = list()
    try:
        data = con.execute('select * from nfruns where workflow = ? order by "start_epochtime" desc', (flow_name,)).fetchall()
    except:
        print("Error accessing DB")
    closeDBConn(con)
    return data

def getRun(flow_name: str, run_uuid: int):
    con = getDBConn()
    data = list()
    try:
        data = con.execute('select * from nfruns where uuid = ? order by "start_epochtime" desc', (run_uuid,)).fetchall()  
    except:
        print("Error accessing DB")
    closeDBConn(con)
    return data

def insertDummyRun(data: dict, db_dir: pathlib.Path = pathlib.Path.cwd()):
    # insert a dummy entry into the table so that the user sees that a run is starting
    # this is replaced when the nextflow process starts
    con = getDBConn(db_dir)
    con.execute('insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (time.strftime("%Y-%m-%d %H:%M:%S"), '-', '-', 'STARTING', '-', 
               '-', '-', data['user'], data['sample_group'], data['workflow'], 
               data['context'], data['root_dir'], data['output_str'], data['run_uuid'], 
               str(int(time.time())), '-', '-', str(int(time.time()))))
    con.commit()
    closeDBConn(con)

def insertRun(s: list, uuid: int, db_dir: pathlib.Path = pathlib.Path.cwd()):
    # add the run to the sqlite database
    con = getDBConn(db_dir)
    # delete dummy entry now that nextflow has started
    print ("deleting dummy run")
    con.execute("delete from nfruns where run_uuid = ?", (uuid,))
    print ("entering actual run")
    con.execute("insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", s)
    con.commit()
    closeDBConn(con)

def reinsertRun(s: list, uuid: int, internal_uuid: int, db_dir: pathlib.Path = pathlib.Path.cwd()):
    # update sqlite database with the end results
    con = getDBConn(db_dir)
    con.execute("delete from nfruns where uuid = ?", (internal_uuid,))
    con.execute("insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", s)
    con.commit()
    closeDBConn(con)

if __name__ == '__main__':
    exit(main())
