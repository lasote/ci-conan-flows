import copy
import json
import multiprocessing
import tempfile
from typing import Dict, Callable

from conan_ci.model.build import Build
from conan_ci.model.build_configuration import BuildConfiguration
from conan_ci.model.build_create_info import BuildCreateInfo
from conan_ci.model.node_info import NodeInfo
from conan_ci.model.repos_build import ReposBuild
from conan_ci.test.mocks.git import GitRepo
from conan_ci.tools import environment_append, chdir


class TravisAPICallerMock(object):
    """Not multiprocess, it will launch the job in the same process"""
    _run_processes: Dict[str, BuildCreateInfo]

    def __init__(self, travis):
        self.travis = travis
        self._run_processes = {}

    def call_build(self, create_info: BuildCreateInfo):

        env = {"CONAN_CI_BUILD_JSON": json.dumps(create_info.dumps())}

        self.travis.fire_build("company/build_node", "master", "Launching Job", env)

        self._run_processes[create_info.node_info.id] = create_info

    def check_ended(self):
        node_infos = self._run_processes.values()
        self._run_processes = {}
        return node_infos

    def empty_queue(self):
        return len(self._run_processes) == 0


class TravisAPICallerMultiThreadMock(object):
    _run_processes: Dict[str, BuildCreateInfo]
    _end_processes: Dict[str, BuildCreateInfo]

    def __init__(self, travis):
        self.travis = travis
        self._run_processes = {}
        self._end_processes = {}

    def call_build(self, create_info: BuildCreateInfo):

        env = {"CONAN_CI_BUILD_JSON": json.dumps(create_info.dumps())}

        args = ("company/build_node", "master", "Launching Job", env)
        p = multiprocessing.Process(target=self.travis.fire_build, args=args)
        p.start()
        create_info.running_id = p

        self._run_processes[create_info.node_info.id] = create_info

    def check_ended(self):
        node_infos = []
        for node_id, node_info in self._run_processes.items():
            if not node_info.running_id.is_alive():
                self._end_processes[node_id] = node_info
                node_infos.append(node_info)
        for node_info in node_infos:
            del self._run_processes[node_info.node_info.id]
        return node_infos

    def empty_queue(self):
        return len(self._run_processes) == 0


class TravisMock(object):

    # https://docs.travis-ci.com/user/environment-variables/#default-environment-variables

    repos: Dict[str, GitRepo]
    env_vars: Dict[str, Dict[str, str]]
    actions: Dict[str, Callable]
    build_counters: Dict[str, int]  # Per slug

    def __init__(self):
        self.repos = {}
        self.env_vars = {}
        self.actions = {}
        self.build_counters = {}

    def register_repo(self, repo_slug: str, repo: GitRepo, action: Callable):
        self.repos[repo_slug] = repo
        self.actions[repo_slug] = action

    def register_env_vars(self, repo_slug, env):
        self.env_vars[repo_slug] = copy.copy(env)

    def increment_build_number(self, slug):
        if slug not in self.build_counters:
            self.build_counters[slug] = 0
        self.build_counters[slug] += 1

    def fire_pr(self, pr_num: int,
                dest_slug: str, dest_branch: str,
                origin_slug: str, origin_branch: str):

        build_folder = tempfile.mkdtemp()

        # Clone the repo
        local_repo = GitRepo(build_folder)
        local_repo.clone(self.repos[origin_slug].folder)
        local_repo.checkout(origin_branch)

        # TODO: make the merge with the origin?
        self.increment_build_number(dest_slug)
        env = {"TRAVIS_BRANCH": dest_branch,
               "TRAVIS_PULL_REQUEST": str(pr_num),
               "TRAVIS_PULL_REQUEST_BRANCH": origin_branch,
               "TRAVIS_BUILD_DIR": local_repo.folder,
               "TRAVIS_COMMIT": local_repo.get_commit(),
               "TRAVIS_PULL_REQUEST_SLUG": dest_slug,
               "TRAVIS_REPO_SLUG": origin_slug,
               "TRAVIS_BUILD_NUMBER": str(self.build_counters[dest_slug])}

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

        self.increment_build_number(slug)
        travis_env = {"TRAVIS_BRANCH": branch,
                      "TRAVIS_COMMIT_MESSAGE": commit_message,
                      "TRAVIS_BUILD_DIR": local_repo.folder,
                      "TRAVIS_COMMIT": local_repo.get_commit(),
                      "TRAVIS_REPO_SLUG": slug,
                      "TRAVIS_BUILD_NUMBER": str(self.build_counters[slug])}

        api_environ.update(travis_env)
        api_environ.update(self.env_vars[slug])

        with environment_append(api_environ):
            with chdir(build_folder):
                self.actions[slug]()
