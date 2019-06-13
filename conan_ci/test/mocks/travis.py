import copy
import tempfile
from multiprocessing import Process

from typing import Dict, Callable

from conan_ci.ci import MainJob, BuildPackageJob
from conan_ci.ci_adapters import TravisCIAdapter
from conan_ci.test.mocks.git import GitRepo
from conan_ci.tools import environment_append, chdir


class TravisAPICallerMock(object):

    def __init__(self, travis):
        self.travis = travis

    def call_build(self, repo_slug: str, branch: str, env: Dict[str, str]):
        self.travis.run_build(repo_slug, branch, env)
        return []

    def wait(self, build_ids):
        return


class TravisAPICallerMultiThreadMock(object):

    def __init__(self, travis):
        self.travis = travis
        self._run_processes = {}

    def call_build(self, node_id: str, ref: str,
                   project_lock_path: str, remote_results_path: str,
                   read_remote_name: str, upload_remote_name: str):

        env = {"CONAN_CI_NODE_ID": node_id,
               "CONAN_CI_REFERENCE": ref,
               "CONAN_CI_READ_REMOTE_NAME": read_remote_name,
               "CONAN_CI_UPLOAD_REMOTE_NAME": upload_remote_name,
               "CONAN_CI_PROJECT_LOCK_PATH": project_lock_path,
               "CONAN_CI_REMOTE_RESULTS_PATH": remote_results_path}

        p = Process(target=self.travis.fire_build,
                    args=("company/build_node", "master", "Launching Job", env))
        p.start()
        self._run_processes[p.pid] = p
        return p.pid

    def wait(self, build_ids):
        for pid, process in self._run_processes.items():
            if pid in build_ids:
                process.join()
        return


class TravisMock(object):

    # https://docs.travis-ci.com/user/environment-variables/#default-environment-variables

    # REGISTRAR REPOS Y SCRIPTS (REPASAR FEATURE MARIA), TRAVIS HACE UN FIRE_PR y un FIRE_BUILD
    # AL FIRE_BUILD RECIBIRA REPO Y RAMA SOLO

    repos: Dict[str, GitRepo]
    env_vars: Dict[str, Dict[str, str]]
    actions: Dict[str, Callable]

    def __init__(self):
        self.repos = {}
        self.env_vars = {}
        self.actions = {}

    def register_repo(self, repo_slug: str, repo: GitRepo, action: Callable):
        self.repos[repo_slug] = repo
        self.actions[repo_slug] = action

    def register_env_vars(self, repo_slug, env):
        self.env_vars[repo_slug] = copy.copy(env)

    def fire_pr(self, pr_num: int,
                dest_slug: str, dest_branch: str,
                origin_slug: str, origin_branch: str):

        build_folder = tempfile.mkdtemp()

        # Clone the repo
        local_repo = GitRepo(build_folder)
        local_repo.clone(self.repos[origin_slug].folder)
        local_repo.checkout(origin_branch)

        # TODO: make the merge with the origin?
        env = {"TRAVIS_BRANCH": dest_branch,
               "TRAVIS_PULL_REQUEST": str(pr_num),
               "TRAVIS_PULL_REQUEST_BRANCH": origin_branch,
               "TRAVIS_BUILD_DIR": local_repo.folder,
               "TRAVIS_COMMIT": local_repo.get_commit(),
               "TRAVIS_PULL_REQUEST_SLUG": dest_slug,
               "TRAVIS_REPO_SLUG": origin_slug,
               "TRAVIS_BUILD_NUMBER": "1"}

        env.update(self.env_vars[origin_slug])

        with environment_append(env):
            with chdir(build_folder):
                self.actions[origin_slug]()

    def fire_build(self, slug: str, branch: str, commit_message: str, api_environ: Dict[str, str]):

        build_folder = tempfile.mkdtemp()

        # Clone the repo
        local_repo = GitRepo(build_folder)
        local_repo.clone(self.repos[slug].folder)
        local_repo.checkout(branch)

        travis_env = {"TRAVIS_COMMIT_MESSAGE": commit_message,
                      "TRAVIS_BUILD_DIR": local_repo.folder,
                      "TRAVIS_COMMIT": local_repo.get_commit(),
                      "TRAVIS_REPO_SLUG": slug,
                      "TRAVIS_BUILD_NUMBER": "1"}

        api_environ.update(travis_env)
        api_environ.update(self.env_vars[slug])

        with environment_append(api_environ):
            with chdir(build_folder):
                self.actions[slug]()
