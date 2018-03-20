import subprocess
import pathlib
import typing
import shlex

import os
import signal

from flask import Flask, request, render_template, redirect, abort

import nflib
import config

app = Flask(__name__)

cfg = config.Config()
cfg.load("config.yaml")

flows = {}
for x in cfg.get('nextflows'):
    flows[x['name']] = x
    

# source: https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks
def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]

@app.route('/')
def list_flows():
    return render_template('list_flows.template', flows=cfg.get('nextflows'))

@app.route('/flow/<flow_name>/new', methods=['GET', 'POST'])
def begin_run(flow_name: str):
    if request.method == 'GET':
        flow_cfg = flows[flow_name]
        flow_input_cfg = flow_cfg['input']
        return render_template('begin_run.template', flow=flow_cfg, incfg=flow_input_cfg)

    elif request.method == 'POST':
        flow_cfg = flows[flow_name]
        flow_input_cfg = flow_cfg['input']
        context = request.form['context']
        vs = list()
        print(flow_input_cfg['type'])
        if flow_input_cfg['type'] == 'file':
            for k,v in request.form.items():
                if k[0:4] == "file":
                    vs.append(v)

        cmd_line = None
        for c in flow_cfg['contexts']:
            print(c)
            if c['name'] == context:
                cmd_line = c['script']
                break
        input_str = flow_input_cfg['argf'].format(*vs)

        cmd = "nohup bash {0} {1} &".format(shlex.quote(cmd_line), shlex.quote(input_str))
        print(cmd)
        os.system(cmd)
        return redirect("/flow/{0}".format(flow_name))

@app.route('/list_all')
def list_all_runs():
    data = list()
    for flow in flows:
        nf_directory = pathlib.Path(flow['directory'])
        table = nflib.parseHistoryFile(nf_directory / 'history')
        table.reverse()
        datum = { 'table': table, 'flow_name': flow['name'] }
        data.append(datum)
    return render_template('list_runs.template', data=data)

@app.route('/flow/<flow_name>')
def list_runs(flow_name : str):
    data = list()
    try:
        flow_cfg = flows[flow_name]
    except:
        abort(404)
    nf_directory = pathlib.Path(flow_cfg['directory'])
    table = nflib.parseHistoryFile(nf_directory / 'history')
    table.reverse()
    datum = { 'table': table, 'flow_name': flow_name }
    data.append(datum)
    return render_template('list_runs.template', data=data)

@app.route('/flow/<flow_name>/details/<run_uuid>')
def run_details(flow_name : str, run_uuid: int):
    nf_directory = pathlib.Path(flows[flow_name]['directory'])

    buttons = { }
    pid_filename = pathlib.Path(flows[flow_name]['directory']) / 'pids' / "{0}.pid".format(run_uuid)
    if pid_filename.is_file():
        buttons['stop'] = True
    else:
        buttons['delete'] = True
        buttons['rerun'] = True
    log_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / '.nextflow.log'
    if log_filename.is_file():
        buttons['log'] = True
    report_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'report.html'
    if report_filename.is_file():
        buttons['report'] = True
    timeline_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'timeline.html'
    if timeline_filename.is_file():
        buttons['timeline'] = True
    dagdot_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'dag.dot'
    if dagdot_filename.is_file():
        buttons['dagdot'] = True

    trace_filename = nf_directory / 'traces/{0}.trace'.format(run_uuid)
    if not trace_filename.is_file():
        abort(404)
    trace_nt = nflib.parseTraceFile(trace_filename)
    return render_template('run_details.template', uuid=run_uuid, flow_name=flow_name, entries=trace_nt, buttons=buttons)

@app.route('/flow/<flow_name>/log/<run_uuid>')
def show_log(flow_name : str, run_uuid: int):
    log_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / '.nextflow.log'
    content = None
    with open(str(log_filename)) as f:
        content = f.read()

    return render_template('show_log.template', content=content, flow_name=flow_name, uuid=run_uuid)

@app.route('/flow/<flow_name>/report/<run_uuid>')
def show_report(flow_name : str, run_uuid: int):
    report_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'report.html'
    with open(str(report_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/timeline/<run_uuid>')
def show_timeline(flow_name: str, run_uuid: int):
    timeline_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'timeline.html'
    with open(str(timeline_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/dagdot/<run_uuid>')
def show_dagdot(flow_name: str, run_uuid: int):
    dagdot_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'dag.dot'
    with open(str(dagdot_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/stop/<run_uuid>')
def kill_nextflow(flow_name : str, run_uuid: int):
    pid_filename = pathlib.Path(flows[flow_name]['directory']) / 'pids' / pathlib.Path("{0}.pid".format(run_uuid)).name
    if pid_filename.is_file():
        pid = None
        with open(str(pid_filename)) as f:
            pid = int(f.readline())
        if pid:
            try:
                print("killing pid {0}".format(pid))
                os.kill(pid, signal.SIGTERM)
            except:
                pass
    return redirect("/flow/{0}/details/{1}".format(flow_name, run_uuid), code=302)
