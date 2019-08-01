import os
import subprocess
import tempfile
from typing import Dict

from conan_ci.tools import chdir, load


class GitRepo(object):

    def __init__(self, folder=None):
        if folder:
            self.folder = folder
        else:
            self.folder = tempfile.mkdtemp()

    def run(self, command: str):
        with chdir(self.folder):
            ret = os.system(command)
            if ret != 0:
                raise Exception("Command failed: {}".format(command))

    def init(self):
        self.run("git init .")
        self.config()
        self.run("git co -b develop")

    def config(self):
        self.run("git config user.email you@example.com")
        self.run("git config user.name pepe")

    def clone(self, url: str):
        self.run("git clone {} .".format(url))
        self.config()

    def add_remote(self, name: str, url: str):
        self.run("git remote add {} {}".format(name, url))

    def remote_remove(self, name: str):
        self.run("git remote remove {}".format(name))

    def fetch(self, name: str):
        self.run("git fetch {}".format(name))

    def checkout(self, branch_name: str):
        self.run("git checkout {}".format(branch_name))

    def checkout_copy(self, branch_name: str):
        self.run("git checkout -b {}".format(branch_name))

    def read_file(self, filename):
        return load(os.path.join(self.folder, filename))

    def commit_files(self, files_contents: Dict[str, str], message: str):
        for file, contents in files_contents.items():
            path = os.path.join(self.folder, file)
            with open(path, "w") as f:
                f.write(contents)
        self.run("git add .")
        self.run("git commit -m \"{}\"".format(message))

    def merge(self, dest_branch: str, remote_url: str, remote_branch: str, merge_message=""):
        try:
            # Might already have it from a previous pr
            self.run("git remote add tmp {}".format(remote_url))
        except:
            pass
        self.run("git fetch tmp")
        self.run("git checkout {}".format(dest_branch))
        if merge_message:
            self.run("git merge --no-ff remotes/tmp/{} -m \"{}\"".format(remote_branch,
                                                                         merge_message))
        else:
            self.run("git merge remotes/tmp/{}".format(remote_branch))

    def get_commit(self):
        tmp = subprocess.check_output("git rev-parse HEAD".split(" "),
                                      cwd=self.folder).decode().strip()
        return tmp

    def get_branch(self):
        status = subprocess.check_output("git status -bs --porcelain".split(" "),
                                         cwd=self.folder).decode()
        # ## feature/scm_branch...myorigin/feature/scm_branch
        branch = status.splitlines()[0].split("...")[0].strip("#").strip()
        return branch

