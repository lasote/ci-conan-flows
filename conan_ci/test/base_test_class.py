import json
import os
import tempfile
import unittest

from conan_ci.artifactory import Artifactory, MetaRepo
from conan_ci.ci_adapters import TravisCIAdapter
from conan_ci.jobs.coordinator_job import CoordinatorJob
from conan_ci.jobs.create_job import ConanCreateJob
from conan_ci.json_logger import JsonLogger
from conan_ci.model.repos_build import ReposBuild
from conan_ci.runner import run
from conan_ci.test.mocks.github import GithubMock
from conan_ci.test.mocks.travis import TravisMock, TravisAPICallerMultiThreadMock
from conan_ci.tools import environment_append, chdir


class BaseTest(unittest.TestCase):

    repo_meta: MetaRepo

    def init(self, pre_develop_repo_name, develop_repo_name, meta_repo_name, slug_prefix="company",
             arti_url=None, arti_user=None, arti_password=None):

        self.slug_prefix = slug_prefix
        self.arti_url = arti_url or "http://localhost:8090/artifactory"
        self.arti_user = arti_user or "admin"
        self.arti_password = arti_password or "password"
        self.art = Artifactory(self.arti_url, self.arti_user, self.arti_password)

        self.develop_repo_name = develop_repo_name
        self.pre_develop_repo_name = pre_develop_repo_name
        self.meta_repo_name = meta_repo_name

        self.travis = TravisMock()
        self.github = GithubMock(self.travis)

        self.repo_develop = self.art.create_repo(develop_repo_name)
        self.repo_pre_develop = self.art.create_repo(pre_develop_repo_name)
        try:
            self.repo_meta = self.art.create_repo(meta_repo_name).as_meta()
        except:
            meta = self.art.get_repo(meta_repo_name)
            meta.remove()
            self.repo_meta = self.art.create_repo(meta_repo_name).as_meta()
        self.logger = JsonLogger()

        # Register a repo in travis that will be the one building single jobs
        self.register_build_repo()

    def _slug(self, ref):
        name = ref.split("@")[0].split("/")[0]
        return "{}/{}".format(self.slug_prefix, name)

    def tearDown(self):
        self.repo_develop.remove()
        self.repo_pre_develop.remove()
        repos = self.art.list_repos()
        for r in repos:
            if r.name.startswith("{}_".format(self.slug_prefix)):
                r.remove()

    def get_travis_env(self):
        travis_env = {"CONAN_LOGIN_USERNAME": self.arti_user,
                      "CONAN_PASSWORD": self.arti_password,
                      "ARTIFACTORY_URL": self.arti_url,
                      "ARTIFACTORY_USER": self.arti_user,
                      "ARTIFACTORY_PASSWORD": os.getenv("ARTIFACTORY_PASSWORD", "password"),
                      "CONAN_REVISIONS_ENABLED": os.getenv("CONAN_REVISIONS_ENABLED", "1")}

        return travis_env

    def populate_meta_repo(self, profiles, project_refs):
        for name, contents in profiles.items():
            self.repo_meta.deploy_contents("profiles/{}".format(name), contents)
        p_json = {"projects": project_refs, "repos_branches": {"develop": self.develop_repo_name}}
        self.repo_meta.deploy_contents("config.json", json.dumps(p_json))

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

    def register_build_repo(self):
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

        self.travis.register_env_vars(slug, self.get_travis_env())
        self.travis.register_repo(slug, repo, action)

    def create_gh_repo(self, slug, files):
        if self.github.repos.get(slug):
            return

        # Register the repo on Github
        repo = self.github.create_repository(slug, files)

        # Register the repo on travis
        self.travis.register_env_vars(slug, self.get_travis_env())

        def main_action():
            """
            This simulates the yml script of a repository of a library
            :return:
            """
            ci_adapter = TravisCIAdapter()
            # TravisAPICallerMock(self.travis)
            ci_caller = TravisAPICallerMultiThreadMock(self.travis)
            art = Artifactory(os.getenv("ARTIFACTORY_URL"),
                              os.getenv("ARTIFACTORY_USER"),
                              os.getenv("ARTIFACTORY_PASSWORD"))
            repos = ReposBuild(art.get_repo(self.develop_repo_name),
                               art.get_repo(self.pre_develop_repo_name),
                               art.get_repo(self.meta_repo_name).as_meta())
            main_job = CoordinatorJob(ci_adapter, ci_caller, self.logger, repos)
            with environment_append({"CONAN_USER_HOME": os.getcwd()}):
                main_job.run()

        self.travis.register_repo(slug, repo, main_action)

        tmp = tempfile.mkdtemp()
        for name, contents in files.items():
            path = os.path.join(tmp, name)
            with open(path, "w") as f:
                f.write(contents)

        return tmp

    def run_conan_commands(self, commands, package_id_mode, folder=None):
        output = ""
        tmp = folder or tempfile.mkdtemp()

        with environment_append({"CONAN_USER_HOME": tmp,
                                 "CONAN_REVISIONS_ENABLED": "1",
                                 "CONAN_LOGIN_USERNAME": self.arti_user,
                                 "CONAN_PASSWORD": self.arti_password,
                                 "CONAN_NON_INTERACTIVE": "1"}):
            with chdir(tmp):
                run("conan config set general.default_package_id_mode={}".format(package_id_mode))
                for c in commands:
                    output += run(c)

        return tmp, output
