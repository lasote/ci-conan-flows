import json
import os
import re
import shutil
import tempfile

import time

from conan_ci.artifactory import Artifactory
from conan_ci.tools import chdir, run_command, run_command_output, load


class BuildPackageJob(object):
    """To build a single node using a lockfile"""

    def __init__(self):

        art_url = os.environ["ARTIFACTORY_URL"]
        art_user = os.environ["ARTIFACTORY_USER"]
        art_password = os.environ["ARTIFACTORY_PASSWORD"]
        art = Artifactory(art_url, art_user, art_password)

        self.repo_read = art.get_repo(os.environ["CONAN_CI_READ_REMOTE_NAME"])
        self.repo_upload = art.get_repo(os.environ["CONAN_CI_UPLOAD_REMOTE_NAME"])
        self.results_remote_path = os.environ["CONAN_CI_REMOTE_RESULTS_PATH"]
        self.project_lock_remote_path = os.environ["CONAN_CI_PROJECT_LOCK_PATH"]
        self.repo_meta = art.get_meta()
        self.ref = os.environ["CONAN_CI_REFERENCE"]

    def run(self):
        print("\n\n\n------------------------------------------------------")
        print("BUILDING '{}' AT '{}'".format(self.ref, os.getcwd()))
        build_folder = os.getcwd()
        try:
            run_command('conan remote remove conan-center')
        except Exception:
            pass
        run_command('conan remote add upload_remote {}'.format(self.repo_upload.url))
        run_command('conan remote add central_remote {}'.format(self.repo_read.url))

        # Download the lock file to the install folder
        self.repo_meta.download_node_lock(self.project_lock_remote_path, build_folder)
        run_command("conan graph clean-modified {}".format(build_folder))
        run_command('conan remove "*" -f')

        # Build the ref using the lockfile
        print("\n\n****************** INSTALL OUTPUT {} ************************".format(self.ref))
        try:
            print("CONAN USER HOME: {}".format(os.getenv("CONAN_USER_HOME")))
            output = run_command_output("conan install {} --install-folder {} "
                                        "--use-lock --build {}".format(self.ref, build_folder,
                                                                       self.ref))
        except Exception as exc:
            self.repo_meta.store_install_log(self.results_remote_path, str(exc))
            self.repo_meta.store_failure(self.results_remote_path)
            raise exc

        print(output)
        print("************************************************************\n\n")

        self.repo_meta.store_install_log(self.results_remote_path, output)

        # Upload the packages
        run_command('conan upload {} --all -r upload_remote'.format(self.ref))

        # Upload the modified lockfile to the right location
        self.repo_meta.store_node_lock(build_folder, self.results_remote_path)
        print("\n\n\n------------------------------------------------------")
        self.repo_meta.store_success(self.results_remote_path)


def get_pull_request_from_message(commit_message):
    node_regex = re.compile(r'.*#(\d+).*')
    ret = node_regex.match(commit_message)
    if not ret:
        return None
    return ret.group(1)


class MainJob(object):
    """To attend a PR or a regular build of a branch"""

    def __init__(self, ci_adapter, ci_caller):

        self.ci_adapter = ci_adapter
        self.ci_caller = ci_caller

        art_url = os.getenv("ARTIFACTORY_URL")
        art_user = os.getenv("ARTIFACTORY_USER")
        art_password = os.getenv("ARTIFACTORY_PASSWORD")

        self.art = Artifactory(art_url, art_user, art_password)

    def run(self):
        try:
            self.ci_adapter.get_key("pr_number")
        except KeyError:
            message = self.ci_adapter.get_key("commit_message")
            pr_number = get_pull_request_from_message(message)
            if pr_number:
                self.run_merge(pr_number)
            else:
                self.run_job()
        else:
            self.run_pr()

    def run_pr(self):
        job = PRJob(self.art, self.ci_adapter, self.ci_caller)
        job.run()

    def run_merge(self, pr_number):

        print("Merging {}".format(pr_number))
        # Copy the packages to the other repo

        # Repeat the build in develop
        self.run_job()

    def run_job(self):
        """Regular job, push to develop for example"""
        pass


class PRJob(object):

    def __init__(self, art, ci_adapter, ci_caller):
        self.art = art
        self.ci_caller = ci_caller
        self.repo_meta = self.art.get_meta()

        current_slug = ci_adapter.get_key("slug")
        pr_number = ci_adapter.get_key("pr_number")
        commit = ci_adapter.get_key("commit")
        dest_branch = ci_adapter.get_key("dest_branch")
        build_number = ci_adapter.get_key("build_number")

        self.build_unique_id = "{}_PR{}_{}_{}".format(current_slug.replace("/", "_"), pr_number,
                                                      commit, build_number)

        self.repo_read = self.art.get_repo(dest_branch)
        self.repo_upload = self.art.create_repo(self.build_unique_id)
        self.checkout_folder = os.getcwd()

    def run(self):

        try:
            run_command('conan remote remove conan-center')
        except Exception:
            pass
        run_command('conan remote add upload_remote {}'.format(self.repo_upload.url))
        run_command('conan remote add central_remote {}'.format(self.repo_read.url))

        profiles_names = self.repo_meta.get_profile_names()
        projects_refs = self.repo_meta.get_projects_refs()
        # Run N conan-create in parallel, one per lockfile
        # TODO: We should do here the same than c3i, infos to calculate
        #  different package id?
        #  conan info <ref> -if=<path_to_lock> --use-lock --json
        for project_ref in projects_refs:
            for profile_name in profiles_names:
                install_folder = os.getcwd()

                # Generate the lock file for the project
                self.generate_lockfile(project_ref, profile_name)

                # Download the lock file to the install folder
                self.download_lockfile(project_ref, profile_name, install_folder)
                run_command('conan remove "*" -f')

                # Get the reference of the node being modified
                name, version = self.inspect_name_and_version(self.checkout_folder)
                ref = "{}/{}@conan/stable".format(name, version)
                run_command("conan export {} {} "
                            "--install-folder {} "
                            "--use-lock".format(self.checkout_folder, ref, install_folder))
                run_command('conan upload {} -r upload_remote'.format(ref))

                def _call_build(the_node_id, the_ref):
                    # Remote lock file path
                    project_lock_path = self.repo_meta.project_lock_path(self.build_unique_id,
                                                                         project_ref,
                                                                         profile_name)
                    the_ref = the_ref.split(":")[0].split("#")[0]
                    remote_results_path = self.repo_meta.node_lock_path(self.build_unique_id,
                                                                        project_ref,
                                                                        profile_name, the_ref,
                                                                        the_node_id)
                    self.ci_caller.call_build(the_node_id, the_ref, project_lock_path,
                                              remote_results_path, self.repo_read.name,
                                              self.repo_upload.name)

                # Get the modified nodes corresponding to the node being modified
                # (could be several?)
                lock = json.loads(load(os.path.join(install_folder, "conan.lock")))["graph_lock"]
                for node_id, data in lock["nodes"].items():
                    if data.get("modified", False):
                        ref = data["pref"].split(":")[0].split("#")[0]
                        _call_build(node_id, ref)

                while not self.ci_caller.empty_queue():
                    print("Sleeping 10 secs")
                    time.sleep(10)
                    ended = self.ci_caller.check_ended()
                    for node_info in ended:
                        # Check status
                        status = self.repo_meta.get_status(node_info.lock_path)
                        if not status:
                            log = self.repo_meta.get_log(node_info.lock_path)
                            raise Exception("The job '{}' failed with "
                                            "error: {}".format(node_info.ref, log))

                        # Get the generated lockfile
                        tmp_path = tempfile.mkdtemp()
                        self.repo_meta.download_node_lock(node_info.lock_path, tmp_path)

                        # Update main lock with the node one
                        new_lock_path = self.update_lockfile(project_ref, profile_name, tmp_path)

                        # Get new build order to iterate the new available nodes
                        groups = self.get_build_order(new_lock_path)
                        if groups:
                            first_group = groups[0]
                            for new_node_id, new_ref in first_group:
                                _call_build(new_node_id, new_ref)

                        shutil.rmtree(tmp_path)
                        shutil.rmtree(new_lock_path)

    @staticmethod
    def inspect_name_and_version(folder):
        json_path = os.path.join(folder, "nv.json")
        run_command("conan inspect {} -a name -a version --json {}".format(folder, json_path))
        with open(json_path) as f:
            c = f.read()
        os.unlink(json_path)
        data = json.loads(c)
        installed = data["name"]
        version = data["version"]
        return installed, version

    @staticmethod
    def get_build_order(install_folder):
        with chdir(install_folder):
            json_path = os.path.join(install_folder, "bo.json")
            run_command('conan graph build-order {} --json {}'.format(install_folder, json_path))
            with open(json_path) as f:
                data = json.load(f)
                return data

    def download_lockfile(self, ref, profile_name, dest_folder):
        remote_path = self.repo_meta.project_lock_path(self.build_unique_id, ref, profile_name)
        self.repo_meta.download_node_lock(remote_path, dest_folder)

    def generate_lockfile(self, ref, profile_name):
        tmp_path = tempfile.mkdtemp()
        profile_path = self.repo_meta.download_profile(profile_name, tmp_path)
        run_command("conan graph lock {} "
                    "--profile {} --install-folder {}".format(ref, profile_path, tmp_path))
        remote_path = self.repo_meta.project_lock_path(self.build_unique_id, ref, profile_name)
        self.repo_meta.store_node_lock(tmp_path, remote_path)
        shutil.rmtree(tmp_path)

    def update_lockfile(self, project_ref, profile_name, origin_folder):
        tmp_path = tempfile.mkdtemp()
        self.download_lockfile(project_ref, profile_name, tmp_path)
        run_command("conan graph update-lock {} {}".format(tmp_path, origin_folder))
        remote_path = self.repo_meta.project_lock_path(self.build_unique_id, project_ref,
                                                       profile_name)
        self.repo_meta.store_node_lock(tmp_path, remote_path)
        return tmp_path
