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
import json

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
    con.execute("CREATE TABLE if not exists nfruns (date_time, duration, code_name, status, hash, uuid, command_line, user, sample_group, workflow, context, root_dir, output_arg, output_dir, run_uuid primary key not null, start_epochtime, pid, ppid, end_epochtime, output_name, data_json);")
    con.execute("CREATE TABLE if not exists nffiles (uuid primary key not null, input_files_count int, output_files_count int, input_files, output_files)")
    con.commit()
    return con

def closeDBConn(con: sqlite3.Cursor):
    con.commit()
    con.close()

def getStatus():
    # the root page lists the current running runs and the last 5 successful and failed runs
    con = getDBConn()
    running = recent = failed = list()
    running = con.execute('select * from nfruns where status = "-" order by "start_epochtime" desc').fetchall()
    recent = con.execute('select * from nfruns where status = "OK" order by "start_epochtime" desc limit 5').fetchall()
    failed = con.execute('select * from nfruns where status = "ERR" or status = "FAIL" order by "start_epochtime" desc limit 5').fetchall()

    closeDBConn(con)
    return (running, recent, failed)

def getWorkflow(flow_name: str):
    con = getDBConn()
    data = list()
    data = con.execute('select * from nfruns where workflow = ? order by "start_epochtime" desc', (flow_name,)).fetchall()
    closeDBConn(con)
    return data

def getRun(flow_name: str, run_uuid: int):
    con = getDBConn()
    data = list()
    data = con.execute('select * from nfruns where uuid = ? order by "start_epochtime" desc', (run_uuid,)).fetchall()
    closeDBConn(con)
    return data

def get_run_uuid_from_internal_uuid(flow_name: str, uuid: int):
    con = getDBConn()
    data = list()
    data = con.execute('select run_uuid from nfruns where uuid = ?', (uuid,)).fetchall()
    print(data)
    closeDBConn(con)
    return data

def insert_files_table(uuid, input_files_count, input_files):
    con = getDBConn()
    con.execute('insert into nffiles values (?,?,?,?,?)', (uuid, input_files_count, -1, input_files, ""))
    closeDBConn(con)

def update_files_table(uuid, output_files_count, output_files):
    con = getDBConn()
    con.execute('update nffiles set output_files_count = ? and output_files = ? where uuid=?', (output_files_count, output_files, uuid))
    closeDBConn(con)

def get_input_files_count(uuid):
    con = getDBConn()
    data = con.execute('select input_files_count, output_files_count from nffiles where uuid = ?', (uuid,)).fetchall()
    closeDBConn(con)
    print(data)
    if not data:
        return [-1,-1]
    else:
        return data[0]

def insertDummyRun(data: dict, db_dir: pathlib.Path = pathlib.Path.cwd()):
    # insert a dummy entry into the table so that the user sees that a run is starting
    # this is replaced when the nextflow process starts
    con = getDBConn(db_dir)
    con.execute('insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (time.strftime("%Y-%m-%d %H:%M:%S"), '-', '-', 'STARTING', '-', 
               '-', '-', data['user'], data['sample_group'], data['workflow'], 
               data['context'], data['root_dir'], data['output_arg'], data['output_dir'], data['run_uuid'], 
               str(int(time.time())), '-', '-', str(int(time.time())), data['output_name'], json.dumps(data)))
    con.commit()
    closeDBConn(con)

def insertRun(s: list, uuid: int, db_dir: pathlib.Path = pathlib.Path.cwd()):
    # add the run to the sqlite database
    con = getDBConn(db_dir)
    # delete dummy entry now that nextflow has started
    print ("deleting dummy run")
    con.execute("delete from nfruns where run_uuid = ?", (uuid,))
    print ("entering actual run")
    con.execute("insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", s)
    con.commit()
    closeDBConn(con)

def reinsertRun(s: list, uuid: int, internal_uuid: int, db_dir: pathlib.Path = pathlib.Path.cwd()):
    # update sqlite database with the end results
    con = getDBConn(db_dir)
    con.execute("delete from nfruns where uuid = ?", (internal_uuid,))
    con.execute("insert into nfruns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", s)
    con.commit()
    closeDBConn(con)

if __name__ == '__main__':
    exit(main())
