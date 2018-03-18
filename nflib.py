import csv
import yaml
from collections import namedtuple
import pathlib
import typing
import glob
import config

HistoryEntry = namedtuple('HistoryEntry', ['date_time', 'duration', 'code_name', 'status', 'hash', 'uuid', 'command_line'])

def parseHistoryFile(nf_history_fp: pathlib.Path) -> typing.List[HistoryEntry]:
    history_nt = list()

    with open(nf_history_fp) as history_file:
        history_tsv = csv.reader(history_file, delimiter='\t')
        for row in history_tsv:
            history_nt.append(HistoryEntry(*row))

    return history_nt

# The trace file fields are vary depending on run parameters
TraceEntry = typing.Dict[str, str]

def parseTraceFile(nf_trace_fp: pathlib.Path) -> typing.List[TraceEntry]:
    traces = list()

    with open(nf_trace_fp) as trace_file:
        reader = csv.DictReader(trace_file, delimiter='\t')
        for row in reader:
            traces.append(row)

    return traces

if __name__ == '__main__':
    exit(main())
