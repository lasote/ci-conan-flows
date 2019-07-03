import copy
import multiprocessing
import tempfile
from typing import Dict, Callable

from conan_ci.ci_adapters import NodeBuilding
from conan_ci.test.mocks.git import GitRepo
from conan_ci.tools import environment_append, chdir


class TravisAPICallerMultiThreadMock(object):
    _run_processes: Dict[str, NodeBuilding]
    _end_processes: Dict[str, NodeBuilding]

    def __init__(self, travis):
        self.travis = travis
        self._run_processes = {}
        self._end_processes = {}

    def _repeated_node_id(self, node_id):
        for d in [self._run_processes, self._end_processes]:
            for _, process_id in d.items():
                if process_id.node_id == node_id:
                    return True
        return False

    def call_build(self, node_id: str, profile_name: str, ref: str,
                   project_lock_path: str, remote_results_path: str,
                   read_remote_name: str, upload_remote_name: str):

        if self._repeated_node_id(node_id):
            print("Already launched: {}".format(node_id))
            return

        env = {"CONAN_CI_NODE_ID": node_id,
               "CONAN_CI_REFERENCE": ref,
               "CONAN_CI_READ_REMOTE_NAME": read_remote_name,
               "CONAN_CI_UPLOAD_REMOTE_NAME": upload_remote_name,
               "CONAN_CI_PROJECT_LOCK_PATH": project_lock_path,
               "CONAN_CI_REMOTE_RESULTS_PATH": remote_results_path}

        args = ("company/build_node", "master", "Launching Job", env)
        p = multiprocessing.Process(target=self.travis.fire_build, args=args)
        p.start()

        self._run_processes[node_id] = NodeBuilding(node_id, ref, remote_results_path,
                                                    p, profile_name)

    def check_ended(self):
        node_infos = []
        for node_id, node_info in self._run_processes.items():
            if not node_info.element.is_alive():
                self._end_processes[node_id] = node_info
                node_infos.append(node_info)
        for node_info in node_infos:
            del self._run_processes[node_info.node_id]
        return node_infos

    def empty_queue(self):
        return len(self._run_processes) == 0


class TravisMock(object):

    # https://docs.travis-ci.com/user/environment-variables/#default-environment-variables

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

        travis_env = {"TRAVIS_BRANCH": branch,
                      "TRAVIS_COMMIT_MESSAGE": commit_message,
                      "TRAVIS_BUILD_DIR": local_repo.folder,
                      "TRAVIS_COMMIT": local_repo.get_commit(),
                      "TRAVIS_REPO_SLUG": slug,
                      "TRAVIS_BUILD_NUMBER": "1"}

        api_environ.update(travis_env)
        api_environ.update(self.env_vars[slug])

        with environment_append(api_environ):
            with chdir(build_folder):
                self.actions[slug]()
