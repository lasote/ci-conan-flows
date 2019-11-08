import uuid
import shutil

from conan_ci.test.base_test_class import BaseTest

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
    
    def build(self):
        self.output.info("Building %s" % self.name)
        for d in os.listdir(self.build_folder):
            p = os.path.join(self.build_folder, d, "myfile.txt")
            if os.path.isfile(p):
                self.output.info("While building: DEP FILE %s: %s" % (d, tools.load(p)))
    
    def package_info(self):
        self.output.info("SELF FILE: %s"
            % tools.load(os.path.join(self.package_folder, "myfile.txt")))
        for d in os.listdir(self.package_folder):
            p = os.path.join(self.package_folder, d, "myfile.txt")
            if os.path.isfile(p):
                self.output.info("DEP FILE %s: %s" % (d, tools.load(p)))


"""

linux_gcc_64 = """
[settings]
os=Linux
os_build=Linux
arch=x86_64
arch_build=x86_64
compiler=gcc
compiler.version=7
compiler.libcxx=libstdc++
build_type=Release
[options]
[build_requires]
[env]
"""


def get_conanfile(ref, reqs):
    name, version = ref.split("@")[0].split("/")
    rand = uuid.uuid4()
    reqs_str = ",".join('"{}"'.format(r) for r in reqs)
    reqs_line = 'requires = {}'.format(reqs_str) if reqs else ""
    cf = conanfile.format(name, version, reqs_line, rand)
    return cf


linux_gcc_32 = linux_gcc_64.replace("x86_64", "x86")


meta_repo_name = "meta"
pre_develop_repo_name = "pre-dev"
develop_repo_name = "dev"


class TestBasic(BaseTest):

    def setUp(self):
        super(TestBasic, self).init(pre_develop_repo_name, develop_repo_name, meta_repo_name,
                                    slug_prefix="company")

    def _prepare_tree(self, tree):
        for ref, deps in tree.items():
            files = {"conanfile.py": get_conanfile(ref, deps),
                     "myfile.txt": "Base {} contents".format(ref)}
            folder = self.create_gh_repo(self._slug(ref), files=files)
            # Upload only the recipes to the repository
            commands = ["conan remote add develop {}".format(self.repo_develop.url),
                        "conan export . {}".format(ref),
                        "conan upload {} -r develop -c --all".format(ref)]
            tmp, _ = self.run_conan_commands(commands, package_id_mode="package_revision_mode",
                                             folder=folder)
            shutil.rmtree(tmp)

    def test_quick(self):
        projects = ["P1/1.0@conan/stable"]
        profiles = {"linux_gcc_64": linux_gcc_64,
                    "linux_gcc_32": linux_gcc_64.replace("x86_64", "x86")}
        self.populate_meta_repo(profiles, projects)

        tree = {"P1/1.0@conan/stable": ["AA/1.0@conan/stable"],
                "AA/1.0@conan/stable": []}
        self._prepare_tree(tree)

        # Create a branch on AA an open pull request
        repo_a = self.github.repos["company/AA"]
        repo_a.checkout_copy("feature/a_improved")
        message_commit = "Here we go!"
        repo_a.commit_files({"myfile.txt": "Modified myfile: I'm modified AA"}, message_commit)

        # We don't use forks because the env vars wouldn't be available
        pr_a = self.github.open_pull_request("company/AA", "develop",
                                             "company/AA", "feature/a_improved")

        self.github.merge_pull_request("company/AA", pr_a)


        input("stop. press a key")

    def test_merge_flow_basic(self):
        projects = ["P1/1.0@conan/stable"]
        profiles = {"linux_gcc_64": linux_gcc_64}
        self.populate_meta_repo(profiles, projects)

        tree = {"P1/1.0@conan/stable": ["BB/1.0@conan/stable", "CC/1.0@conan/stable"],
                "BB/1.0@conan/stable": ["AA/1.0@conan/stable"],
                "CC/1.0@conan/stable": ["AA/1.0@conan/stable"],
                "AA/1.0@conan/stable": []}

        self._prepare_tree(tree)

        # Create a branch on AA an open pull request
        repo_a = self.github.repos["company/AA"]
        repo_a.checkout_copy("feature/a_improved")
        message_commit = "Here we go!"
        repo_a.commit_files({"myfile.txt": "Modified myfile: I'm modified AA"}, message_commit)

        # We don't use forks because the env vars wouldn't be available
        pr_a = self.github.open_pull_request("company/AA", "develop",
                                             "company/AA", "feature/a_improved")

        # Create a branch on CC an open pull request
        repo_c = self.github.repos["company/CC"]
        repo_c.checkout_copy("feature/c_improved")
        message_commit = "Here we go with CC!"
        repo_c.commit_files({"myfile.txt": "Modified myfile: I'm modified CC"}, message_commit)

        # We don't use forks because the env vars wouldn't be available
        pr_c = self.github.open_pull_request("company/CC", "develop",
                                             "company/CC", "feature/c_improved")

        # We merge PR_A and then we merge PR_B
        self.github.merge_pull_request("company/CC", pr_c)
        self.github.merge_pull_request("company/AA", pr_a)

        # Asserts
        commands = ["conan remote add develop {}".format(self.repo_develop.url),
                    "conan install P1/1.0@conan/stable"]
        _, output = self.run_conan_commands(commands, package_id_mode="package_revision_mode")
        expected = """SELF FILE: Base P1/1.0@conan/stable contents
P1/1.0@conan/stable: DEP FILE AA: Modified myfile: I'm modified AA
P1/1.0@conan/stable: DEP FILE CC: Modified myfile: I'm modified CC
P1/1.0@conan/stable: DEP FILE BB: Base BB/1.0@conan/stable contents
"""
        self.assertIn(expected, output)


""" 
    def test_merge_flow_conflict(self):
        projects = ["P1"]
        profiles = {"linux_gcc_64": linux_gcc_64}
        tree = {"P1": ["BB", "CC"],
                "BB": ["AA"],
                "CC": ["AA"]}

        tree = self._complete_refs(tree)
        projects = [self._complete_ref(p) for p in projects]

        self._store_meta(profiles, projects)

        for p in projects:
            self.create_gh_repo(tree, p, upload_recipe=True)

        # Register a repo in travis that will be the one building single jobs
        self.register_build_repo()

        # Create a branch on AA an open pull request
        repo_a = self.github.repos[self.get_slug("AA")]
        repo_a.checkout_copy("feature/a_improved")
        message_commit = "Here we go!"
        repo_a.commit_files({"myfile.txt": "Modified myfile: I'm modified AA"}, message_commit)

        # We don't use forks because the env vars wouldn't be available
        pr_a = self.github.open_pull_request("company/AA", "develop",
                                             "company/AA", "feature/a_improved")

        # Create another branch on AA an open pull request
        repo_a = self.github.repos[self.get_slug("AA")]
        repo_a.checkout_copy("feature/a_super_improved")
        message_commit = "Here we go! Super Improving!"
        repo_a.commit_files({"myfile.txt": "Modified myfile: I'm modified AA. Super improved!"
                                           "And super modified."}, message_commit)

        # We don't use forks because the env vars wouldn't be available
        pr_a_super = self.github.open_pull_request("company/AA", "develop",
                                                   "company/AA", "feature/a_super_improved")

        # Create a branch on CC an open pull request
        repo_c = self.github.repos[self.get_slug("CC")]
        repo_c.checkout_copy("feature/c_improved")
        message_commit = "Here we go with CC!"
        repo_c.commit_files({"myfile.txt": "Modified myfile: I'm modified CC"}, message_commit)

        # We don't use forks because the env vars wouldn't be available
        pr_c = self.github.open_pull_request("company/CC", "develop",
                                             "company/CC", "feature/c_improved")

        # We merge PR_A and then we merge PR_B
        # FIXME: Wait for the PRs to be built

        self.github.wait_for_pr(pr_a)
        self.github.wait_for_pr(pr_a_super)
        self.github.wait_for_pr(pr_c)

        self.github.merge_pull_request("company/CC", pr_c)
        self.github.merge_pull_request("company/AA", pr_a)
        self.github.merge_pull_request("company/AA", pr_a_super)
        # TODO: asserts
        print("Breakpoint")
"""
