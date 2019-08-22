import datetime
import os
import shutil
import tempfile
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
    try:
        old_path = os.getcwd()
    except:
        old_path = None
    os.chdir(newdir)
    try:
        yield
    finally:
        if old_path and os.path.exists(old_path):
            os.chdir(old_path)


def iso_now():
    return datetime.datetime.utcnow().isoformat().split(".")[0] + ".000Z"


@contextmanager
def tmp_folder():
    tmp_path = tempfile.mkdtemp()
    try:
        with chdir(tmp_path):
            yield tmp_path
    finally:
        shutil.rmtree(tmp_path)


def cur_folder():
    return os.getcwd().replace("\\", "/")


def load(path, binary=False):
    """ Loads a file content """
    with open(path, 'rb') as handle:
        tmp = handle.read()
        return tmp if binary else tmp.decode()

