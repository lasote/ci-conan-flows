import os
import subprocess
from contextlib import contextmanager
from subprocess import Popen, PIPE, STDOUT


@contextmanager
def environment_append(env_vars):
    unset_vars = []
    for key in env_vars.keys():
        if env_vars[key] is None:
            unset_vars.append(key)
    for var in unset_vars:
        env_vars.pop(var, None)
    for name, value in env_vars.items():
        if isinstance(value, list):
            env_vars[name] = os.pathsep.join(value)
            old = os.environ.get(name)
            if old:
                env_vars[name] += os.pathsep + old
    if env_vars or unset_vars:
        old_env = dict(os.environ)
        os.environ.update(env_vars)
        for var in unset_vars:
            os.environ.pop(var, None)
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(old_env)
    else:
        yield


@contextmanager
def chdir(newdir):
    old_path = os.getcwd()
    os.chdir(newdir)
    try:
        yield
    finally:
        os.chdir(old_path)


def run_command(command):
    print(command)
    ret = os.system(command)
    if ret != 0:
        raise Exception()


def run_command_output(command, cwd=None):

    try:
        # piping both stdout, stderr and then later only reading one will hang the process
        # if the other fills the pip. So piping stdout, and redirecting stderr to stdout,
        # so both are merged and use just a single get_stream_lines() call
        proc = Popen(command, shell=True, stdout=PIPE, stderr=STDOUT, cwd=cwd)
    except Exception as e:
        raise Exception("Error while executing '%s'\n\t%s" % (command, str(e)))

    def get_stream_lines(the_stream):
        ret = []
        while True:
            line = the_stream.readline()
            if not line:
                break
            ret.append(line.decode())
        return "".join(ret)

    output = get_stream_lines(proc.stdout)

    proc.communicate()
    ret = proc.returncode
    if ret != 0:
        raise Exception(output)
    return output


def load(path, binary=False):
    """ Loads a file content """
    with open(path, 'rb') as handle:
        tmp = handle.read()
        return tmp if binary else tmp.decode()
