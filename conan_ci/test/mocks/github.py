from typing import Dict
from conan_ci.test.mocks.git import GitRepo
from conan_ci.test.mocks.travis import TravisMock


class PRInfo(object):
    slug_origin: str
    slug_dest: str
    branch_origin: str
    branch_dest: str

    def __init__(self, slug_origin, branch_origin, slug_dest, branch_dest):
        self.slug_origin = slug_origin
        self.slug_dest = slug_dest
        self.branch_origin = branch_origin
        self.branch_dest = branch_dest


class GithubMock(object):

    repos: Dict[str, GitRepo]
    pr_counter: Dict[str, int]
    pr_info: Dict[int, PRInfo]

    def __init__(self, travis: TravisMock):
        self.travis = travis
        self.repos = {}
        self.pr_counter = {}
        self.pr_info = {}

    def _register_repo(self, repo_slug: str, repo: GitRepo):
        self.repos[repo_slug] = repo
        self.pr_counter[repo_slug] = 0

    def create_repository(self, slug_name: str, files: Dict[str, str]):
        r = GitRepo()
        r.init()
        r.commit_files(files, message="dummy message")
        self._register_repo(slug_name, r)
        return r

    def open_pull_request(self, dest_slug: str, dest_branch, slug: str, branch: str):
        pr_num = self.pr_counter[slug]
        pr_num += 1
        self.travis.fire_pr(pr_num, dest_slug, dest_branch, slug, branch)
        self.pr_info[pr_num] = PRInfo(slug, branch, dest_slug, dest_branch)
        return pr_num

    def merge_pull_request(self, pr_num: int):
        info: PRInfo = self.pr_info[pr_num]
        self.travis.fire_build(info.slug_dest,
                               info.branch_dest,
                               "Merged PR: #{}".format(pr_num),
                               {})
