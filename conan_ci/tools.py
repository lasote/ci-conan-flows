import os
import subprocess
from contextlib import contextmanager


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


def run_command_output(command):
    return subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)


def load(path, binary=False):
    """ Loads a file content """
    with open(path, 'rb') as handle:
        tmp = handle.read()
        return tmp if binary else tmp.decode()
