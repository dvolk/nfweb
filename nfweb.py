#
# nfweb is a simple interface to nextflow using the flask web framework
#

import json
import pathlib
import shlex
import uuid
import os
import signal

from flask import Flask, request, render_template, redirect, abort, url_for
import flask_login

from passlib.hash import bcrypt

import nflib
import config

app = Flask(__name__)
# This is used for signing browser cookies. Change it in prod. Changing it
# invalidates all current user sessions
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

    form_password = request.form['password']
    password_hash = users[form_username]['password']

    user.is_authenticated = bcrypt.verify(form_password, password_hash)
    return user

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.template')
    if request.method == 'POST':
        form_username = request.form['username']
        form_password = request.form['password']
        if form_username in users:
            password_hash = users[form_username]['password']
            if bcrypt.verify(form_password, password_hash):
                user = User()
                user.id = form_username
                flask_login.login_user(user)
                return redirect('/')
        return redirect('/login')

def reload_cfg():
    global cfg
    cfg = config.Config()
    cfg.load("config.yaml")
    global systemCfg
    systemCfg = dict()    
    for c in cfg.get('system')['contexts']:
        print(c)
        systemCfg[c['name']] = c
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
    (running, recent, failed) = nflib.getStatus()
    return render_template('status.template', running=running, recent=recent, failed=failed)

def is_admin():
    return 'admin' in users[flask_login.current_user.id]['capabilities']

@app.route('/userinfo/<username>', methods=['GET', 'POST'])
@flask_login.login_required
def userinfo(username: str):
    is_same = username == flask_login.current_user.id
    username_exists = username in users

    if (not is_same and not is_admin()) or not username_exists:
        return redirect('/')

    if request.method == "POST":
        cur_pw = request.form['currentpassword']
        new_pw1 = request.form['newpassword']
        new_pw2 = request.form['newpassword2']
        password_hash = users[username]['password']
        if bcrypt.verify(cur_pw, password_hash):
            if new_pw1 == new_pw2:
                pass
                flask_login.logout_user()
        return redirect('/')
    else:
        return render_template('userinfo.template', userinfo=users[username])

@app.route('/admin', methods=['GET', 'POST'])
@flask_login.login_required
def admin():
    if not is_admin():
        return redirect('/')

    if request.method == 'GET':
        with open("config.yaml") as f:
            return render_template('admin.template', config_yaml=f.read())
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

        run_context_dict = dict()
        for c in flow_cfg['contexts']:
            run_context_dict[c['name']] = c 

            if 'root_dirs' in systemCfg[c['name']]:
                run_context_dict[c['name']]['root_dir'] = systemCfg[c['name']]['root_dirs'] + flow_cfg['root_dir']
            else:
                run_context_dict[c['name']]['root_dir'] = flow_cfg['root_dir']

            if 'prog_dirs' in systemCfg[c['name']]:
                run_context_dict[c['name']]['prog_dir'] = systemCfg[c['name']]['prog_dirs'] + flow_cfg['prog_dir']
            else:
                run_context_dict[c['name']]['prog_dir'] = flow_cfg['prog_dir']

        return render_template('begin_run.template', flow=flow_cfg, incfg=flow_input_cfg, contextcfg=run_context_dict)

    elif request.method == 'POST':
        flow_cfg = flows[flow_name]
        flow_input_cfg = flow_cfg['input']
        context = request.form['context']

        # get the form user inputs
        vs = list()
        for key in sorted(request.form.keys()):
            if key[0:15] == 'nfwebparaminput':
                vs.append(request.form[key])

        print(len(vs), flow_input_cfg['description'])
        if len(vs) < len(flow_input_cfg['description']):
            return redirect("/flow/{0}/new".format(flow_name))

        run_context_dict = dict()
        for c in flow_cfg['contexts']:
            run_context_dict[c['name']] = c 

        if 'root_dirs' in systemCfg[context]:
            root_dir = systemCfg[context]['root_dirs'] + flow_cfg['root_dir']
        else:
            root_dir = flow_cfg['root_dir']

        if 'prog_dirs' in systemCfg[context]:
            prog_dir = systemCfg[context]['prog_dirs'] + flow_cfg['prog_dir']
        else:
            prog_dir = flow_cfg['prog_dir']

        run_uuid = str(uuid.uuid4())

        # all the data that is passed to go.py (which starts nextflow)
        data = {
            # path to nextflow file relative to the prog_dir
            'nf_filename' : flow_cfg['script'],
            # nextflow work directory
            'root_dir' : root_dir,
            # directory containing nextflow file and misc other files
            'prog_dir' : prog_dir,
            # static arguments to nextflow
            'arguments' : run_context_dict[context]['arguments'],
            # user arguments to nextflow
            'input_str' : flow_input_cfg['argf'].format(*vs),
            # web user id that started the run
            'user': flask_login.current_user.id,
            # nfweb run uuid (not to be confused with the uuid generated by nextflow)
            'run_uuid': run_uuid,
            # placeholder
            'sample_group': 'asdf',
            # workflow name
            'workflow': flow_name,
            # execution context (i.e. local or slurm or whatever)
            'context': context
        }

        try:
            # insert a dummy entry into the table so that the user sees that a run is starting
            # this is replaced when the nextflow process starts
            nflib.insertDummyRun(data)
        except Exception as e:
            print('Error occured entering dummy run into DB.')
            print(e)
            abort(404)

        # convert to json
        data_json = json.dumps(data)

        # launch go.py with data as the argument (carefully shell escaped)
        cmd = "python3 go.py {0} &".format(shlex.quote(data_json))
        print(cmd)
        os.system(cmd)
        return redirect("/flow/{0}".format(flow_name))

@app.route('/flow/<flow_name>')
@flask_login.login_required
def list_runs(flow_name : str):
    data = list()
    try:
        flow_cfg = flows[flow_name]
    except:
        abort(404)

    data = nflib.getWorkflow(flow_name)
    return render_template('list_runs.template', stuff={ 'flow_name': flow_cfg['name'] }, data=data)

@app.route('/flow/<flow_name>/details/<run_uuid>')
@flask_login.login_required
def run_details(flow_name : str, run_uuid: int):
    print( flow_name, " with uuid ", run_uuid)
    data = nflib.getRun(flow_name, run_uuid)
    # root_dir is entry 11
    nf_directory = pathlib.Path(data[0][11])

    buttons = { }
    pid_filename = nf_directory / 'pids' / "{0}.pid".format(run_uuid)
    if pid_filename.is_file():
        buttons['stop'] = True
    else:
        # TODO: make this work
        buttons['delete'] = True
        # TODO: make this work
        buttons['rerun'] = True
    log_filename = nf_directory / 'maps' / run_uuid / '.nextflow.log'
    if log_filename.is_file():
        buttons['log'] = True
    report_filename = nf_directory / 'maps' / run_uuid / 'report.html'
    if report_filename.is_file():
        buttons['report'] = True
    timeline_filename = nf_directory / 'maps' / run_uuid / 'timeline.html'
    if timeline_filename.is_file():
        buttons['timeline'] = True
    dagdot_filename = nf_directory / 'maps' / run_uuid / 'dag.dot'
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
    try:
        data = nflib.getRun(flow_name, run_uuid)
    except Exception as e:
        print('Error occured getting run info.')
        print(e)
        abort(404)

    # Using root_dir
    log_filename = pathlib.Path(data[0][11]) / 'maps' / run_uuid / '.nextflow.log'
    content = None
    with open(str(log_filename)) as f:
        content = f.read()

    return render_template('show_log.template', content=content, flow_name=flow_name, uuid=run_uuid)

@app.route('/flow/<flow_name>/report/<run_uuid>')
@flask_login.login_required
def show_report(flow_name : str, run_uuid: int):
    try:
        data = nflib.getRun(flow_name, run_uuid)
    except Exception as e:
        print('Error occured getting run info.')
        print(e)
        abort(404)

    # Using root_dir
    report_filename = pathlib.Path(data[0][11]) / 'maps' / run_uuid / 'report.html'
    with open(str(report_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/timeline/<run_uuid>')
@flask_login.login_required
def show_timeline(flow_name: str, run_uuid: int):
    try:
        data = nflib.getRun(flow_name, run_uuid)
    except Exception as e:
        print('Error occured getting run info.')
        print(e)
        abort(404)

    # Using root_dir
    timeline_filename = pathlib.Path(data[0][11]) / 'maps' / run_uuid / 'timeline.html'
    with open(str(timeline_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/dagdot/<run_uuid>')
@flask_login.login_required
def show_dagdot(flow_name: str, run_uuid: int):
    try:
        data = nflib.getRun(flow_name, run_uuid)
    except Exception as e:
        print('Error occured getting run info.')
        print(e)
        abort(404)

    # Using root_dir
    dagdot_filename = pathlib.Path(data[0][11]) / 'maps' / run_uuid / 'dag.dot'
    with open(str(dagdot_filename)) as f:
        return f.read()

@app.route('/flow/<flow_name>/stop/<run_uuid>')
@flask_login.login_required
def kill_nextflow(flow_name : str, run_uuid: int):
    try:
        data = nflib.getRun(flow_name, run_uuid)
    except Exception as e:
        print('Error occured getting run info.')
        print(e)
        abort(404)

    # Using root_dir
    pid_filename = pathlib.Path(data[0][11]) / 'pids' / pathlib.Path("{0}.pid".format(run_uuid)).name
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
