import json
import os
import tempfile
import unittest
import uuid

from conan_ci.artifactory import Artifactory
from conan_ci.ci import MainJob, BuildPackageJob
from conan_ci.ci_adapters import TravisCIAdapter
from conan_ci.test.mocks.github import GithubMock
from conan_ci.test.mocks.travis import TravisMock, TravisAPICallerMultiThreadMock
from conan_ci.tools import environment_append, chdir, run_command

conanfile = """
import os
from conans import ConanFile, tools

class MyConanfile(ConanFile):
    settings = "os", "arch", "build_type", "compiler"
    name = "{}"
    version = "{}"
    exports_sources = "myfile.txt"
    keep_imports = True
    {}
    
    # comment {}
                    
    def imports(self):
        self.copy("myfile.txt", folder=True)
    def package(self):
        self.copy("*myfile.txt")
    def package_info(self):
        self.output.info("SELF FILE: %s"
            % tools.load(os.path.join(self.package_folder, "myfile.txt")))
        for d in os.listdir(self.package_folder):
            p = os.path.join(self.package_folder, d, "myfile.txt")
            if os.path.isfile(p):
                self.output.info("DEP FILE %s: %s" % (d, tools.load(p)))


"""

linux_gcc7_64 = """
[settings]
os=Linux
os_build=Linux
arch=x86_64
arch_build=x86_64
compiler=gcc
compiler.version=7
compiler.libcxx=libstdc++11
build_type=Release
[options]
[build_requires]
[env]
"""

linux_gcc7_32 = linux_gcc7_64.replace("x86_64", "x86")


travis_env = { "CONAN_LOGIN_USERNAME": "admin",
               "CONAN_PASSWORD": "password",
               "ARTIFACTORY_URL": "http://localhost:8090/artifactory",
               "ARTIFACTORY_USER": "admin",
               "ARTIFACTORY_PASSWORD": "password",
               "CONAN_REVISIONS_ENABLED": "1"}


class TestBasic(unittest.TestCase):

    def setUp(self):
        self.art = Artifactory("http://localhost:8090/artifactory", "admin", "password")
        self.repo_develop = self.art.create_repo("develop")
        self.repo_meta = self.art.create_repo("meta")
        self.travis = TravisMock()
        self.github = GithubMock(self.travis)

    def tearDown(self):
        self.repo_meta.remove()
        self.repo_develop.remove()
        repos = self.art.list_repos()
        for r in repos:
            r.remove()

    def _store_meta(self, profiles, project_refs):
        for name, contents in profiles.items():
            self.repo_meta.deploy_contents("profiles/{}".format(name), contents)
        p_json = {"projects": project_refs}
        self.repo_meta.deploy_contents("projects.json", json.dumps(p_json))

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
        files = {"conanfile.py": cf, "myfile.txt": "From {}".format(ref)}

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
            ci_caller = TravisAPICallerMultiThreadMock(self.travis)
            main_job = MainJob(ci_adapter, ci_caller)
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
                                     "CONAN_LOGIN_USERNAME": "admin", "CONAN_PASSWORD": "password",
                                     "CONAN_NON_INTERACTIVE": "1"}):
                with chdir(tmp):
                    run_command("conan remote add develop {}".format(self.repo_develop.url))
                    run_command("conan export . {}".format(ref))
                    run_command("conan upload {} -r develop -c --all".format(ref))

        for req in reqs:
            self.create_gh_repo(tree, req, upload_recipe=upload_recipe)

    def register_build_repo(self):
        slug = "company/build_node"
        repo = self.github.create_repository(slug, {"foo": "bar"})
        repo.checkout_copy("master")  # By default the mock creates develop

        def action():
            """
            This simulates the yml script of a repository of a library
            :return:
            """
            main_job = BuildPackageJob()
            with environment_append({"CONAN_USER_HOME": os.getcwd()}):
                main_job.run()

        self.travis.register_env_vars(slug, travis_env)
        self.travis.register_repo(slug, repo, action)

    def test_basic(self):
        projects = ["P1", "P2"]
        profiles = {"linux_gcc7_64": linux_gcc7_64, "linux_gcc7_32": linux_gcc7_32}
        """  tree = {"P1": ["FF", "CC", "DD", "EE"],
                "P2": ["FF"],
                "CC": ["BB"],
                "DD": ["BB"],
                "BB": ["AA"],
                "FF": ["AA"],
                "AA": [],
                "EE": []}"""

        tree = {"P1": ["AA"],
                "P2": ["AA"]}

        tree = self._complete_refs(tree)
        projects = [self._complete_ref(p) for p in projects]

        self._store_meta(profiles, projects)

        for p in projects:
            self.create_gh_repo(tree, p, upload_recipe=True)

        # Register a repo in travis that will be the one building single jobs
        self.register_build_repo()

        # Create a branch on AA an open pull request
        repo = self.github.repos[self.get_slug("AA")]
        repo.checkout_copy("feature/cool1")
        cf = repo.read_file("conanfile.py")
        repo.commit_files({"conanfile.py": cf + "\n\n"}, "Here we go!")

        # Generate binary for EE merging the PR
        # pr_number = self.github.open_pull_request("lasote/EE", "company/EE")
        # self.github.merge_pull_request(pr_number)

        # We don't use forks because the env vars wouldn't be available
        self.github.open_pull_request("company/AA", "develop", "company/AA", "feature/cool1")

        # TODO: asserts






