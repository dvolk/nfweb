#
# nfweb is a simple interface to nextflow using the flask web framework
#

import json
import pathlib
import shlex
import uuid
import os
import subprocess
import signal
from collections import deque

from flask import Flask, request, render_template, redirect, abort, url_for
import flask_login

from ldap3 import Connection

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

        if auth == 'ldap':
            print(cfg.get('ldap'))
            conn = Connection(cfg.get('ldap')[0]['host'], user=form_username, password=form_password, read_only=True)
            if conn.bind():
                print("ldap user {0} logged in".format(form_username))
                user = User()
                user.id = form_username
                flask_login.login_user(user)

                cap = []
                if form_username in cfg.get('ldap')[0]['admins']:
                    cap = ['admin']

                short_username, domain = form_username.split('@')

                users[user.id] = {
                    'name': form_username,
                    'capabilities' : cap,
                    'short_username': short_username,
                    'domain': domain
                }
                
                return redirect('/')
            else:
                print("invalid credentials for ldap user {0}".format(form_username))
        if auth == 'builtin':
            if form_username in users:
                password_hash = users[form_username]['password']
                if bcrypt.verify(form_password, password_hash):
                    print("user {0} logged in".format(form_username))
                    user = User()
                    user.id = form_username
                    flask_login.login_user(user)
                    return redirect('/')
                else:
                    print("invalid credentials for user {0}".format(form_username))

        # login fail
        return redirect('/login')

def reload_cfg():
    global cfg
    cfg = config.Config()
    cfg.load("config.yaml")
    global auth
    auth = cfg.get('authentication')
    global systemCfg
    systemCfg = dict()
    for c in cfg.get('contexts'):
        systemCfg[c['name']] = c
    global flows
    flows = dict()
    for f in cfg.get('nextflows'):
        flows[f['name']] = f
    global users
    users = dict()
    for u in cfg.get('users'):
        users[u['name']] = u
    global ldap
    ldap = dict()
    for l in cfg.get('ldap'):
        ldap[l['name']] = l
    print(ldap)

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
        flow_param_cfg = flow_cfg['param']

        run_context_dict = dict()
        current_user = users[flask_login.current_user.id]
        ldap_short_username = current_user['short_username']
        ldap_domain = current_user['domain']
        print(ldap[ldap_domain])
        user_output_permissions = ldap[ldap_domain]['user_output_permissions']

        for c in flow_cfg['contexts']:
            run_context_dict[c['name']] = c 

            # Append directories to context root if present
            if 'root_dirs' in systemCfg[c['name']]:
                run_context_dict[c['name']]['root_dir'] = pathlib.Path(systemCfg[c['name']]['root_dirs']) / flow_cfg['root_dir']
            else:
                raise Exception("No 'root_dirs' in config.")

            if 'prog_dirs' in systemCfg[c['name']]:
                run_context_dict[c['name']]['prog_dir'] = pathlib.Path(systemCfg[c['name']]['prog_dirs']) / flow_cfg['prog_dir']
            else:
                raise Exception("No 'prog_dirs' in config.")

            if 'output_dirs' in systemCfg[c['name']]:
                run_context_dict[c['name']]['output_dir'] = pathlib.Path(systemCfg[c['name']]['output_dirs'].format(user = flask_login.current_user.id, ldap_short_username = ldap_short_username, ldap_domain = ldap_domain)) / flow_cfg['root_dir']
            else:
                run_context_dict[c['name']]['output_dir'] = pathlib.Path(run_context_dict[c['name']]['root_dir']) / 'output' / flask_login.current_user.id

        return render_template('begin_run.template', flow=flow_cfg, paramcfg=flow_param_cfg, contextcfg=run_context_dict)

    elif request.method == 'POST':
        flow_cfg = flows[flow_name]
        flow_param_cfg = flow_cfg['param']
        flow_output_cfg = flow_cfg['output']
        context = request.form['context']

        current_user = users[flask_login.current_user.id]
        ldap_short_username = current_user['short_username']
        ldap_domain = current_user['domain']
        user_output_permissions = ldap[ldap_domain]['user_output_permissions']

        run_context_dict = dict()
        for c in flow_cfg['contexts']:
            run_context_dict[c['name']] = c

        # TODO Generate in same method as GET method
        if 'root_dirs' in systemCfg[context]:
            root_dir = pathlib.Path(systemCfg[context]['root_dirs']) /  flow_cfg['root_dir'] / flask_login.current_user.id
        else:
            raise Exception("No 'root_dirs' in config.")

        if 'prog_dirs' in systemCfg[context]:
            prog_dir = pathlib.Path(systemCfg[context]['prog_dirs']) / flow_cfg['prog_dir']
        else:
            raise Exception("No 'prog_dirs' in config.")

        if 'output_dirs' in systemCfg[context]:
            output_dir = pathlib.Path(systemCfg[context]['output_dirs'].format(user = flask_login.current_user.id, ldap_short_username = ldap_short_username, ldap_domain = ldap_domain)) / flow_cfg['root_dir']
        else:
            output_dir = root_dir / 'output' / flask_login.current_user.id

        # get the form user inputs and use them to format the input and output string
        vs = deque([])
        indir = ""
        readpat = ""
        inputs = dict()
        for key in sorted(request.form.keys()):
            if key[0:10] == 'nfwebparam':
                if key[11:16] == 'input':
                    if key[17:21] == 'text':
                        if key[22:] == 'indir':
                            indir = request.form[key]
                        if key[22:] == 'readpat':
                            readpat = request.form[key]
                        if key[22:] in inputs:
                            inputs[key[22:]][1] = request.form[key]
                        else:
                            inputs[key[22:]] = ["", request.form[key]]

                    else:
                        if key[22:] in vs:
                            inputs[key[22:]][0] = request.form[key]
                        else:
                            inputs[key[22:]] = [request.form[key], ""]

                elif key[11:17] == 'output':
                    output_arg = flow_output_cfg['parameter'] 
                    output_dir = output_dir / request.form[key]
                else:
                    for param in flow_param_cfg['description']:
                        if param['name'] == key[11:]:
                            if param['type'] == 'text' or param['type'] == 'list':
                                vs.append("{0} {1}".format(param['arg'], request.form[key]))
                            elif param['type'] == 'switch' and request.form[key] == 'True':
                                vs.append(param['arg'])
        print(vs)



        for inputKey, inputValues in inputs.items():
            for inputInfo in flow_param_cfg['description']:
                if inputInfo['name'] == inputKey:
                    if inputInfo['type'] == 'input-reqr':
                        vs.appendleft("{0} {1}".format(inputInfo['arg'], inputValues[1]))

                    else:
                        for option in inputInfo['options']:
                            if option['option'] == inputValues[0]:
                                vs.appendleft("{0} {1}".format(option['arg'], inputValues[1]))


        run_uuid = str(uuid.uuid4())

        if auth == 'ldap':
            current_user = users[flask_login.current_user.id]
            ldap_short_username = current_user['short_username']
            ldap_domain = current_user['domain']
            user_output_permissions = ldap[ldap_domain]['user_output_permissions']
        else:
            ldap_short_username = ''
            ldap_domain = ''
            user_output_permissions = ''

        data = {
            # path to nextflow file relative to the prog_dir
            'nf_filename' : flow_cfg['script'],
            # nextflow work directory
            'root_dir' : str(root_dir),
            # directory containing nextflow file and misc other files
            'prog_dir' : str(prog_dir),
            # static arguments to nextflow
            'arguments' : run_context_dict[context]['arguments'],
            # user arguments to nextflow
            'input_str' : ' '.join(vs),
            # output argument to use
            'output_arg' : output_arg,
            # output directory
            'output_dir' : str(output_dir),
            # web user id that started the run
            'user': flask_login.current_user.id,
            # nfweb run uuid (not to be confused with the uuid generated by nextflow)
            'run_uuid': run_uuid,
            # placeholder
            'sample_group': 'asdf',
            # workflow name
            'workflow': flow_name,
            # execution context (i.e. local or slurm or whatever)
            'context': context,
            # ldap domain or empty string if not domain
            'ldap_domain': ldap_domain,
            # name
            'output_name': request.form['nfwebparam-output'],
            # user's short (no domain) username if using ldap otherwise empty string
            'ldap_short_username': ldap_short_username,
            # change the output permissions/ownership to the ldap user
            'user_output_permissions': user_output_permissions,
            # input directory (if it exists or "" otherwise)
            'indir': indir,
            # filtering regular expression (if it exists or "" otherwise)
            'readpat': readpat
        }

        try:
            # this is replaced when the nextflow process starts
            nflib.insertDummyRun(data)
        except Exception as e:
            print('Error occured entering dummy run into DB.')
            print(e)
            print(data)
            abort(404)

        # convert to json
        data_json = json.dumps(data)

        # log file to capture the output of go.py to a file
        log_dir = cfg.get('log_dir')
        log_filename = "{0}.log".format(run_uuid)
        log_file =  pathlib.Path(log_dir) / log_filename
        # launch go.py with data as the argument (carefully shell escaped)
        cmd = "( python3 go.py {0} | tee {1} ) &".format(shlex.quote(data_json), log_file)
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
    data = [list(datum) for datum in data]

    for datum in data:
        uuid = datum[14]
        input_files_count, output_files_count = nflib.get_input_files_count(uuid)
        datum.append(input_files_count)
        datum.append(output_files_count)

    #print(data)
    return render_template('list_runs.template', stuff={ 'flow_name': flow_cfg['name'] }, data=data)

@app.route('/flow/<flow_name>/go_details/<uuid>')
@flask_login.login_required
def go_details(flow_name : str, uuid: str):
    # this can be called with either the run_uuid or the internal uuid
    # try it with the run uuid first
    log_dir = cfg.get('log_dir')
    log_filename = "{0}.log".format(uuid)
    log_file =  pathlib.Path(log_dir) / log_filename
    if not log_file.is_file():
        # if it doesn't exist, try to get it by the internal uuid then
        uuids = nflib.get_run_uuid_from_internal_uuid(flow_name, uuid)
        print(uuids)
        if uuids:
            run_uuid = uuids[0][0]
            log_filename = "{0}.log".format(run_uuid)
            log_file =  pathlib.Path(log_dir) / log_filename
    if not log_file.is_file():
            abort(404)
    with open(str(log_file)) as lf:
        return render_template('show_log.template', content=lf.read(), uuid=uuid)

@app.route('/flow/<flow_name>/details/<run_uuid>')
@flask_login.login_required
def run_details(flow_name : str, run_uuid: int):
    print( flow_name, " with uuid ", run_uuid)
    data = nflib.getRun(flow_name, run_uuid)
    # root_dir is entry 11
    nf_directory = pathlib.Path(data[0][11])
    output_dir = pathlib.Path(data[0][13])

    buttons = { 'output_files': True }
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

    trace_filename = nf_directory / 'traces/{0}.trace'.format(run_uuid)
    if not trace_filename.is_file():
        print (trace_filename)
        abort(404)
    trace_nt = nflib.parseTraceFile(trace_filename)
    return render_template('run_details.template', uuid=run_uuid, flow_name=flow_name, entries=trace_nt, output_dir=str(output_dir), buttons=buttons)

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

@app.route('/flow/<flow_name>/output_files/<run_uuid>')
@flask_login.login_required
def show_output_files(flow_name : str, run_uuid: int):
    # run du and tree to display total file size and file tree of output directory
    data = nflib.getRun(flow_name, run_uuid)
    if not data:
        print('Error occured getting run info.')
        abort(404)

    # Using root_dir
    output_dir = data[0][13]

    du_cmd = ["du", "-sh", output_dir]
    tree_cmd = ["tree", output_dir]
    print(du_cmd)
    print(tree_cmd)

    try:
        du_p = subprocess.run(du_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    except:
        print("Failed to run du: {0}".format(du_p.stderr))
        abort(404)
    try:
        tree_p = subprocess.run(tree_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    except:
        print("Failed to run tree: {0}".format(tree_p.stderr))
        abort(404)

    # Format directory on top, then total size, then the file tree
    size_str = du_p.stdout.strip()
    size_str = size_str.split("\t")
    size_str = "Total size: {0}".format(size_str[0])
    out_str = tree_p.stdout.strip().split('\n')
    out_str = "\n".join([out_str[0]] + [out_str[-1]] + [size_str] + [""] + out_str[1:-1])

    return render_template('show_log.template', content=out_str, flow_name=flow_name, uuid=run_uuid)

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
