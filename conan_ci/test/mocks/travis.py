import tempfile

from typing import Dict

from conan_ci.ci import ci_run
from conan_ci.test.mocks.git import GitRepo
from conan_ci.tools import environment_append


class TravisAPICallerMock(object):

    def __init__(self, travis):
        self.travis = travis

    def call_build(self, repo_slug: str, branch: str, env: Dict[str, str]):
        self.travis.run_build(repo_slug, branch, env)
        return []

    def wait(self, build_ids):
        return


class TravisMock(object):

    # https://docs.travis-ci.com/user/environment-variables/#default-environment-variables
    # TRAVIS_BRANCH
    # TRAVIS_BUILD_DIR
    # TRAVIS_COMMIT
    # TRAVIS_JOB_NUMBER
    # TRAVIS_PULL_REQUEST
    # TRAVIS_REPO_SLUG
    travis_api: TravisAPICallerMock
    repos: Dict[str, GitRepo]

    def __init__(self):
        self.travis_api = TravisAPICallerMock(self)
        self.repos = {}

    def register_repo(self, slug: str, repo: GitRepo):
        self.repos[slug] = repo

    def run_pr_build(self, repo_slug: str, origin_repo: GitRepo, origin_branch: str,
                     dest_repo: GitRepo, dest_branch: str):

        build_folder = tempfile.mkdtemp()

        # Clone the repo
        local_repo = GitRepo(build_folder)
        local_repo.clone(origin_repo.folder)
        local_repo.checkout(origin_branch)

        # TODO: make the merge with the origin?
        env = {"TRAVIS_BRANCH": origin_branch,
               "TRAVIS_BUILD_DIR": local_repo.folder,
               "TRAVIS_COMMIT": local_repo.get_commit(),
               "TRAVIS_REPO_SLUG": repo_slug,
               "CONAN_REVISIONS_ENABLED": "1",
               "CONAN_USER_HOME": local_repo.folder,
               "CONAN_LOGIN_USERNAME": "admin",
               "CONAN_PASSWORD": "password"}

        with environment_append(env):
            ci_run(build_folder, self.travis_api, dest_branch, "http://localhost:8090/artifactory",
                   "admin", "password")

    def run_build(self, slug: str, branch: str, env: Dict[str, str]):
        build_folder = tempfile.mkdtemp()

        # Clone the repo
        repo = self.repos[slug]
        local_repo = GitRepo(build_folder)
        local_repo.clone(repo.folder)
        local_repo.checkout(branch)

        env_t = {"TRAVIS_BRANCH": branch,
                 "CONAN_USER_HOME": build_folder,
                 "TRAVIS_REPO_SLUG": slug,
                 "CONAN_REVISIONS_ENABLED": "1",
                 "CONAN_LOGIN_USERNAME": "admin",
                 "CONAN_PASSWORD": "password"}
        env.update(env_t)
        with environment_append(env):
            ci_run(build_folder, self.travis_api, None, "http://localhost:8090/artifactory",
                   "admin", "password")
