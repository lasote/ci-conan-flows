import os
import tempfile
import unittest
import uuid

from conan_ci.artifactory import Artifactory
from conan_ci.jobs.coordinator_job import CoordinatorJob
from conan_ci.ci_adapters import TravisCIAdapter, TravisAPICaller
from conan_ci.jobs.create_job import ConanCreateJob
from conan_ci.runner import run
from conan_ci.test.mocks.github import GithubMock
from conan_ci.test.mocks.travis import TravisMock
from conan_ci.test.test_basic import conanfile
from conan_ci.tools import environment_append, chdir


travis_env = {"CONAN_LOGIN_USERNAME": os.getenv("CONAN_LOGIN_USERNAME", "admin"),
              "CONAN_PASSWORD": os.getenv("CONAN_PASSWORD", "password"),
              "ARTIFACTORY_URL": os.getenv("ARTIFACTORY_URL", "http://localhost:8090/artifactory"),
              "ARTIFACTORY_USER":  os.getenv("ARTIFACTORY_USER", "admin"),
              "ARTIFACTORY_PASSWORD": os.getenv("ARTIFACTORY_PASSWORD", "password"),
              "CONAN_REVISIONS_ENABLED": os.getenv("CONAN_REVISIONS_ENABLED", "1")}

travis_token = os.getenv("TRAVIS_TOKEN", "")


class TestBasic(unittest.TestCase):

    def setUp(self):
        self.art = Artifactory(travis_env["ARTIFACTORY_URL"],
                               travis_env["ARTIFACTORY_USER"],
                               travis_env["ARTIFACTORY_PASSWORD"])
        try:
            self.repo_develop = self.art.create_repo("develop")
        except:
            pass
        self.travis = TravisMock()
        self.github = GithubMock(self.travis)

    @staticmethod
    def _complete_ref(name):
        if "/" not in name:
            return "{}/1.0@conan/stable".format(name)
        return name

    def _complete_refs(self, tree):
        new_tree = {}
        for ref, reqs in tree.items():
            new_tree[self._complete_ref(ref)] = [self._complete_ref(r) for r in reqs]
        return new_tree

    def get_slug(self, name):
        slug = "company/{}".format(name)
        return slug

    def create_gh_repo(self, tree, ref, upload_recipe=True):
        name, version = ref.split("@")[0].split("/")
        slug = self.get_slug(name)
        if self.github.repos.get(slug):
            return
        rand = uuid.uuid4()
        reqs = tree.get(ref, [])
        reqs_str = ",".join('"{}"'.format(r) for r in reqs)
        reqs_line = 'requires = {}'.format(reqs_str) if reqs else ""
        cf = conanfile.format(name, version, reqs_line, rand)
        files = {"conanfile.py": cf, "myfile.txt": "Original content: {}".format(ref)}

        # Register the repo on Github
        repo = self.github.create_repository(slug, files)

        # Register the repo on travis
        self.travis.register_env_vars(slug, travis_env)

        def main_action():
            """
            This simulates the yml script of a repository of a library
            :return:
            """
            ci_adapter = TravisCIAdapter()
            # ci_caller = TravisAPICallerMultiThreadMock(self.travis)
            token = os.getenv("TRAVIS_TOKEN")
            ci_caller = TravisAPICaller(self.travis, "lasote/build_node", token)
            main_job = CoordinatorJob(ci_adapter, ci_caller)
            with environment_append({"CONAN_USER_HOME": os.getcwd()}):
                main_job.run()

        self.travis.register_repo(slug, repo, main_action)

        tmp = tempfile.mkdtemp()
        for name, contents in files.items():
            path = os.path.join(tmp, name)
            with open(path, "w") as f:
                f.write(contents)

        if upload_recipe:
            with environment_append({"CONAN_USER_HOME": tmp,
                                     "CONAN_REVISIONS_ENABLED": "1",
                                     "CONAN_LOGIN_USERNAME": travis_env["CONAN_LOGIN_USERNAME"],
                                     "CONAN_PASSWORD": travis_env["CONAN_PASSWORD"],
                                     "CONAN_NON_INTERACTIVE": "1"}):
                with chdir(tmp):
                    run("conan remote add develop {}".format(self.repo_develop.url))
                    run("conan export . {}".format(ref))
                    run("conan upload {} -r develop -c --all".format(ref))

        for req in reqs:
            self.create_gh_repo(tree, req, upload_recipe=upload_recipe)

    def register_create_repo(self):
        slug = "company/build_node"
        repo = self.github.create_repository(slug, {"foo": "bar"})
        repo.checkout_copy("master")  # By default the mock creates develop

        def action():
            """
            This simulates the yml script of a repository of a library
            :return:
            """
            main_job = ConanCreateJob()
            with environment_append({"CONAN_USER_HOME": os.getcwd()}):
                main_job.run()

        self.travis.register_env_vars(slug, travis_env)
        self.travis.register_repo(slug, repo, action)

    def test_basic(self):
        projects = ["P1", "P2"]
        tree = {"P1": ["FF", "CC", "DD"],
                "P2": ["FF"],
                "CC": ["BB"],
                "DD": ["BB"],
                "BB": ["AA"],
                "FF": ["AA"],
                "AA": []}

        tree = {"P1": ["AA"],
                "P2": ["AA"]}

        tree = self._complete_refs(tree)
        projects = [self._complete_ref(p) for p in projects]

        for p in projects:
            self.create_gh_repo(tree, p, upload_recipe=False)

        # Register a repo in travis that will be the one building single jobs
        self.register_create_repo()

        # Create a branch on AA an open pull request
        repo = self.github.repos[self.get_slug("AA")]
        repo.checkout_copy("feature/cool1")
        message_commit = "Here we go!"
        repo.commit_files({"myfile.txt": "Modified myfile: pepe"}, message_commit)

        # Generate binary for EE merging the PR
        # pr_number = self.github.open_pull_request("lasote/EE", "company/EE")
        # self.github.merge_pull_request(pr_number)

        # We don't use forks because the env vars wouldn't be available
        pr_number = self.github.open_pull_request("company/AA", "develop",
                                                  "company/AA", "feature/cool1")

        self.github.merge_pull_request(pr_number)
        # TODO: asserts
        print("Breakpoint")






