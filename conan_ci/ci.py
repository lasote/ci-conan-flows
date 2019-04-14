import json
import os
from typing import List

import time

from conan_ci.artifactory import Artifactory, ArtifactoryRepo
from conan_ci.tools import chdir


def ci_run(folder, travis_api, dest_branch: str, artifactory_url: str, artifactory_user: str,
           artifactory_password: str):
    action = os.getenv("ACTION")
    current_slug = os.getenv("TRAVIS_REPO_SLUG")
    commit = os.getenv("TRAVIS_COMMIT")
    art = Artifactory(artifactory_url, artifactory_user, artifactory_password)
    runner = CIRunner(folder, travis_api)

    if action is None:
        unique_id = "{}_{}".format(current_slug.replace("/", "_"), commit)
        repo_origin = art.create_repo(unique_id)
        repo_dest = art.get_repo(dest_branch)
        repo_meta = art.get_repo("meta")
        runner.pr_build(current_slug, repo_origin, repo_dest, repo_meta, dest_branch)
    elif action == "LOCKFILES":
        repo_origin = art.get_repo(os.getenv("REPO_ORIGIN"))
        repo_dest = art.get_repo(os.getenv("REPO_DEST"))
        repo_meta = art.get_repo(os.getenv("REPO_META"))
        reference = os.getenv("REFERENCE")
        profiles = repo_meta.list_files("profiles")
        runner.get_project_lockfile_and_orders(reference, current_slug, repo_origin, repo_dest,
                                               repo_meta, profiles)
    elif action == "CREATE":
        repo_origin = art.get_repo(os.getenv("REPO_ORIGIN"))
        repo_dest = art.get_repo(os.getenv("REPO_DEST"))
        lockfile_path = os.getenv("LOCKFILE")
        reference = os.getenv("REFERENCE")
        runner.intermediate_node_build(reference, repo_origin, repo_dest, lockfile_path)


class CIRunner(object):

    def __init__(self, folder, travis_api):
        self.folder = folder
        self.travis_api = travis_api

    def run(self, command: str):
        with chdir(self.folder):
            ret = os.system(command)
            if ret != 0:
                raise Exception("Command failed: {}".format(command))

    @staticmethod
    def _extract_created_ref(json_path):
        with open(json_path) as f:
            c = f.read()
            data = json.loads(c)
            installed = data["installed"]
            for item in installed:
                if item["recipe"]["exported"]:
                    return item["recipe"]["id"]
            return None

    def pr_build(self, current_slug: str, repo_origin: ArtifactoryRepo, repo_dest: ArtifactoryRepo,
                 repo_meta: ArtifactoryRepo, dest_branch: str):
        repo_origin.set_properties({"time": [str(time.time())]})
        # For the final merge, to know the latest commit???

        # ERROR! we don't want to build this package because maybe we are building incorrect ones
        # unless we want to build it to run the tests and so on!

        # Build the package for all the profiles located in the meta repository
        self.run('conan remote remove conan-center')
        self.run('conan remote add upload_remote {}'.format(repo_origin.url))
        self.run('conan remote add central_remote {}'.format(repo_dest.url))
        profiles_names = repo_meta.list_files("profiles")

        ref = ""
        for profile_name in profiles_names:
            profile_path = repo_meta.download_file(self.profile_path(profile_name), self.folder)
            self.run('conan create . conan/stable --profile {} --json xx.json'.format(profile_path))
            ref = self._extract_created_ref(os.path.join(self.folder, "xx.json"))
            self.run('conan upload {} -r upload_remote --all -c'.format(ref))

        # Read the project sleeves
        p = repo_meta.read_file("projects.json")
        project_slugs = json.loads(p)["projects"]

        # Generate the graph-locks and the build orders using the project leaves
        build_ids = []
        for slug in project_slugs:
            env = {"ACTION": "LOCKFILES",
                   "REFERENCE": ref,
                   "REPO_ORIGIN": repo_origin.name,
                   "REPO_DEST": repo_dest.name,
                   "REPO_META": repo_meta.name}
            build_id = self.travis_api.call_build(slug, dest_branch, env=env)
            build_ids.append(build_id)

        self.travis_api.wait(build_ids)

        # Launch the individual builds following the order and applying the graph_lock
        build_ids = []
        for slug in project_slugs:
            for profile_name in profiles_names:
                order = self.read_order(repo_origin, slug, profile_name)
                for group in order:
                    for lib in group:
                        if ref.startswith(lib):  # Ignore RREV
                            lib_repo_slug = current_slug
                        else:
                            # FIXME: Correlate slugs and refs?
                            lib_repo_slug = "company/{}".format(lib.split("/")[0])
                        env = {"LOCKFILE": self.lockfile_name(slug, profile_name),
                               "ACTION": "CREATE",
                               "REFERENCE": lib,
                               "REPO_ORIGIN": repo_origin.name,
                               "REPO_DEST": repo_dest.name,
                               "REPO_META": repo_meta.name}
                        build_id = self.travis_api.call_build(lib_repo_slug, dest_branch, env)
                        # Redirect and capture the output?
                        build_ids.append(build_id)

        self.travis_api.wait(build_ids)

    @staticmethod
    def read_order(repo: ArtifactoryRepo, project_slug: str, profile_name: str):
        t = repo.read_file(CIRunner.build_order_name(project_slug, profile_name))
        data = json.loads(t)["groups"]
        return data

    @staticmethod
    def lockfile_name(project_slug, profile_name):
        return "{}-{}.lock".format(project_slug.replace("/", "-"), profile_name)

    @staticmethod
    def build_order_name(project_slug, profile_name):
        return "{}-{}-order.json".format(project_slug.replace("/", "-"), profile_name)

    @staticmethod
    def profile_path(profile_name):
        return "profiles/{}".format(profile_name)

    def get_project_lockfile_and_orders(self, reference: str, slug: str, repo_origin: ArtifactoryRepo,
                                        repo_dest: ArtifactoryRepo,
                                        repo_meta: ArtifactoryRepo, profiles_names: List):
        self.run('conan remote remove conan-center')
        self.run('conan remote add upload_remote {}'.format(repo_origin.url))
        self.run('conan remote add central_remote {}'.format(repo_dest.url))
        for profile_name in profiles_names:
            clean_dir = os.path.join(self.folder, profile_name)
            os.mkdir(clean_dir)
            self.folder = clean_dir
            lock_name = os.path.join(clean_dir, self.lockfile_name(slug, profile_name))
            build_order_name = os.path.join(clean_dir, self.build_order_name(slug, profile_name))
            profile_path = repo_meta.download_file(self.profile_path(profile_name), clean_dir)
            # self.run("conan install --generate-lockfile={}.lock
            # --profile {}".format(lock_name, profile_path))

            # ###### FAKED LOCKFILE ONLY PROFILE #########
            self.run("conan install .. --profile {}".format(profile_path))
            with open(lock_name, "wb") as f:
                f.write(repo_meta.read_file(self.profile_path(profile_name)))
            #############################################
            repo_origin.deploy(lock_name, os.path.basename(lock_name))
            # ##### FAKED USAGE OF THE LOCKFILE, ONLY THE PROFILE ########
            ref = reference.split("#")[0]  # Remove revision
            self.run("conan info .. --build-order {} "
                     "--profile {} "
                     "--json {}".format(ref, lock_name, build_order_name))
            ##############################################
            repo_origin.deploy(build_order_name, os.path.basename(build_order_name))

    def intermediate_node_build(self, reference: str, repo_origin: ArtifactoryRepo,
                                repo_dest: ArtifactoryRepo, lockfile_path: str):
        self.run('conan remote remove conan-center')
        self.run('conan remote add upload_remote {}'.format(repo_origin.url))
        self.run('conan remote add central_remote {}'.format(repo_dest.url))
        path = repo_origin.download_file(lockfile_path, self.folder)
        # ########## MOCKED LOCKFILE WITH PROFILE
        # self.run('conan create {} conan/stable --lockfile {}'.format(reference, path))
        self.run('conan create . {} --profile {}'.format(reference, path))
        # #######################################
        self.run('conan upload {} --all -r upload_repo'.format(reference))
