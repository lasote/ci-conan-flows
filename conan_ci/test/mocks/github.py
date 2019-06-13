from typing import Dict
from conan_ci.test.mocks.git import GitRepo
from conan_ci.test.mocks.travis import TravisMock


class GithubMock(object):

    repos: Dict[str, GitRepo]
    prCounter: Dict[str, int]

    def __init__(self, travis: TravisMock):
        self.travis = travis
        self.repos = {}
        self.prCounter = {}

    def _register_repo(self, repo_slug: str, repo: GitRepo):
        self.repos[repo_slug] = repo
        self.prCounter[repo_slug] = 0

    def create_repository(self, slug_name: str, files: Dict[str, str]):
        r = GitRepo()
        r.init()
        r.commit_files(files, message="dummy message")
        self._register_repo(slug_name, r)
        return r

    def open_pull_request(self, dest_slug: str, dest_branch, slug: str, branch: str):
        pr_num = self.prCounter[slug]
        pr_num += 1
        self.travis.fire_pr(pr_num, dest_slug, dest_branch, slug, branch)
        return pr_num

    """def merge_pull_request(self, pr_num: int, slug: str, dest_slug: str):
        self.travis.merge_pull_request(slug,
                                       self.repos[slug],
                                       self.repos[slug].get_branch(),
                                       self.repos[dest_slug],
                                       self.repos[slug].get_branch())"""
