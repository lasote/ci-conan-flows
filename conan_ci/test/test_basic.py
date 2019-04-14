import unittest
import uuid

from conan_ci.artifactory import Artifactory
from conan_ci.test.mocks.github import GithubMock
from conan_ci.test.mocks.travis import TravisMock

conanfile = """
from conans import ConanFile

class MyConanfile(ConanFile):
    name="{}"
    version="{}"
    {}
    
    # comment {}

"""

default_profile = """
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


class TestBasic(unittest.TestCase):

    def setUp(self):
        art = Artifactory("http://localhost:8090/artifactory", "admin", "password")
        self.repo_meta = art.create_repo("meta")
        self.repo_meta.deploy_contents(default_profile, "profiles/linux")
        self.repo_meta.deploy_contents('{"projects":  ["company/project1", "company/project2"]}',
                                       "projects.json")

    def test_basic(self):

        travis = TravisMock()

        rand = uuid.uuid4()  # To get different commit and avoid repo collisions
        github = GithubMock(travis)
        github.create_repository("company/zlib",
                                 {"conanfile.py": conanfile.format("zlib", "1.2.8", "", rand)})

        github.create_repository("lasote/zlib",
                                 {"conanfile.py": conanfile.format("zlib", "1.2.8", "", rand)})

        project_cf = conanfile.format("project1", "1.1", 'requires="zlib/1.2.8@conan/stable"', rand)
        github.create_repository("company/project1", {"conanfile.py": project_cf})

        project_cf = conanfile.format("project2", "5.1", 'requires="zlib/1.2.8@conan/stable"',
                                      rand)
        github.create_repository("company/project2", {"conanfile.py": project_cf})

        github.open_pull_request("lasote/zlib", "company/zlib")

    def tearDown(self):
        self.repo_meta.remove()




