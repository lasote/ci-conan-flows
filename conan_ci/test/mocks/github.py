from typing import Dict
from conan_ci.test.mocks.git import GitRepo
from conan_ci.test.mocks.travis import TravisMock


class GithubMock(object):

    repos: Dict[str, GitRepo]

    def __init__(self, travis: TravisMock):
        self.travis = travis
        self.repos = {}

    def _register_repo(self, repo_slug: str, repo: GitRepo):
        self.repos[repo_slug] = repo
        self.travis

    def create_repository(self, slug_name: str, files: Dict[str, str]):
        r = GitRepo()
        r.init()
        r.commit_files(files, message="dummy message")
        self._register_repo(slug_name, r)
        self.travis.register_repo(slug_name, r)

    def open_pull_request(self, slug: str, dest_slug: str):
        self.travis.run_pr_build(slug,
                                 self.repos[slug],
                                 self.repos[slug].get_branch(),
                                 self.repos[dest_slug],
                                 self.repos[slug].get_branch())
