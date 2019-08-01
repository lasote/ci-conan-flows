import multiprocessing
from asyncio import sleep
from multiprocessing import Process
from typing import Dict
from collections import defaultdict
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
    pr_info: Dict[str, Dict[int, PRInfo]]
    pr_processes: Dict[int, Process]

    def __init__(self, travis: TravisMock):
        self.travis = travis
        self.repos = {}
        self.pr_counter = {}
        self.pr_info = defaultdict(dict)
        self.pr_processes = {}

    def _register_repo(self, repo_slug: str, repo: GitRepo):
        self.repos[repo_slug] = repo
        self.pr_counter[repo_slug] = 0

    def create_repository(self, slug_name: str, files: Dict[str, str]):
        r = GitRepo()
        r.init()
        r.commit_files(files, message="dummy message")
        self._register_repo(slug_name, r)
        return r

    def open_pull_request(self, dest_slug: str, dest_branch, slug: str, branch: str, is_async=False):
        print("""
 ██████╗ ██████╗ ███████╗███╗   ██╗    ██████╗ ██████╗ 
██╔═══██╗██╔══██╗██╔════╝████╗  ██║    ██╔══██╗██╔══██╗
██║   ██║██████╔╝█████╗  ██╔██╗ ██║    ██████╔╝██████╔╝
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║    ██╔═══╝ ██╔══██╗
╚██████╔╝██║     ███████╗██║ ╚████║    ██║     ██║  ██║
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝    ╚═╝     ╚═╝  ╚═╝
                                                       
""")
        print("From '{}:{}' to '{}:{}'".format(slug, branch, dest_slug, dest_branch))
        pr_num = self.pr_counter[slug]
        pr_num += 1
        args = (pr_num, dest_slug, dest_branch, slug, branch)
        if is_async:
            p = multiprocessing.Process(target=self.travis.fire_pr, args=args)
            p.start()
            self.pr_processes[pr_num] = p
        else:
            self.travis.fire_pr(*args)
        self.pr_info[dest_slug][pr_num] = PRInfo(slug, branch, dest_slug, dest_branch)
        return pr_num

    def wait_for_pr(self, pr_num: int):
        if pr_num not in self.pr_processes:  # not async
            return
        p = self.pr_processes[pr_num]
        while True:
            if p.is_alive():
                sleep(5)
            else:
                return

    def merge_pull_request(self, slug, pr_num: int):
        print("""
███╗   ███╗███████╗██████╗  ██████╗ ███████╗    ██████╗ ██████╗ 
████╗ ████║██╔════╝██╔══██╗██╔════╝ ██╔════╝    ██╔══██╗██╔══██╗
██╔████╔██║█████╗  ██████╔╝██║  ███╗█████╗      ██████╔╝██████╔╝
██║╚██╔╝██║██╔══╝  ██╔══██╗██║   ██║██╔══╝      ██╔═══╝ ██╔══██╗
██║ ╚═╝ ██║███████╗██║  ██║╚██████╔╝███████╗    ██║     ██║  ██║
╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝    ╚═╝     ╚═╝  ╚═╝
                                                                
""")

        info: PRInfo = self.pr_info[slug][pr_num]
        origin_repo = self.repos[info.slug_origin]

        dest_repo = self.repos[info.slug_dest]

        dest_repo.merge(info.branch_dest, origin_repo.folder, info.branch_origin,
                        "Merging PR#{}".format(pr_num))

        print("PR NUMBER: '{}' to {}/{}".format(pr_num, info.slug_dest, info.branch_dest))
        self.travis.fire_build(info.slug_dest,
                               info.branch_dest,
                               "Merged PR: #{}".format(pr_num),
                               {})
