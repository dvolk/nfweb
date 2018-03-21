import subprocess
import pathlib
import typing
import shlex

import os
import signal

from flask import Flask, request, render_template, redirect, abort, url_for
import flask_login

import nflib
import config

app = Flask(__name__)
app.secret_key = 'secret key'
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
login_manager.login_view = '/login'

class User(flask_login.UserMixin):
    pass

@login_manager.user_loader
def user_loader(username):
    if username not in users:
        return
    user = User()
    user.id = username
    return user

@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    if username not in users:
        return
    user = User()
    user.id = username

    user.is_authenticated = request.form['password'] == users[username]['password']
    return user

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.template')
    if request.method == 'POST':
        username = request.form['username']
        if username in users and request.form['password'] == users[username]['password']:
            user = User()
            user.id = username
            flask_login.login_user(user)
            return redirect('/')
        return redirect('/login')

def reload_cfg():
    global cfg
    cfg = config.Config()
    cfg.load("config.yaml")
    global flows
    flows = dict()
    for f in cfg.get('nextflows'):
        flows[f['name']] = f
    global users
    users = dict()
    for u in cfg.get('users'):
        users[u['name']] = u

reload_cfg()

@app.route('/logout')
def logout():
    flask_login.logout_user()
    return redirect('/')
        
# todo move this and similar to nflib.py
@app.route('/')
@flask_login.login_required
def status():
    running = list()
    for _,flow in flows.items():
        nf_directory = pathlib.Path(flow['directory'])
        table = nflib.parseHistoryFile(nf_directory / 'history')
        for run in table:
            if run.status == "-":
                running.append([flow, run])
    print(running)
    return render_template('status.template', running=running)

@app.route('/userinfo/<username>')
@flask_login.login_required
def userinfo(username: str):
    is_admin = 'admin' in users[flask_login.current_user.id]['capabilities']
    is_same = username == flask_login.current_user.id
    username_exists = username in users

#    if not is_admin or not is_same or not username_exists:
#        return redirect('/')
#    else:
    return render_template('userinfo.template', userinfo=users[username])

@app.route('/admin', methods=['GET', 'POST'])
@flask_login.login_required
def admin():
    if 'admin' not in users[flask_login.current_user.id]['capabilities']:
        return redirect('/')
    
    if request.method == 'GET':
        return render_template('admin.template', config_yaml=open("config.yaml").read())
    if request.method == 'POST':
        if request.form['config']:
            old_cfg = cfg.config
            new_cfg = request.form['config']
            try:
                cfg2 = config.Config()
                cfg2.load_str(new_cfg)
            except:
                print("invalid config string")
                return redirect("/admin")
            try:
                f = open("config.yaml", "w")
                f.write(new_cfg)
            except:
                print("Couldn't write config.yaml file")
                return redirect("/admin")
            finally:
                f.close()
            try:
                reload_cfg()
            except:
                print("couldn't reload config")
                cfg.config = old_cfg
                return redirect("/admin")

        return redirect("/admin")

@app.route('/flows')
@flask_login.login_required
def list_flows():
    return render_template('list_flows.template', flows=cfg.get('nextflows'))

@app.route('/flow/<flow_name>/new', methods=['GET', 'POST'])
@flask_login.login_required
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
@flask_login.login_required
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
@flask_login.login_required
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
@flask_login.login_required
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
@flask_login.login_required
def show_log(flow_name : str, run_uuid: int):
    log_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / '.nextflow.log'
    content = None
    with open(str(log_filename)) as f:
        content = f.read()

    return render_template('show_log.template', content=content, flow_name=flow_name, uuid=run_uuid)

@app.route('/flow/<flow_name>/report/<run_uuid>')
@flask_login.login_required
def show_report(flow_name : str, run_uuid: int):
    report_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'report.html'
    with open(str(report_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/timeline/<run_uuid>')
@flask_login.login_required
def show_timeline(flow_name: str, run_uuid: int):
    timeline_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'timeline.html'
    with open(str(timeline_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/dagdot/<run_uuid>')
@flask_login.login_required
def show_dagdot(flow_name: str, run_uuid: int):
    dagdot_filename = pathlib.Path(flows[flow_name]['directory']) / 'maps' / run_uuid / 'dag.dot'
    with open(str(dagdot_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/stop/<run_uuid>')
@flask_login.login_required
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
