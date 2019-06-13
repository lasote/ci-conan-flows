import json
import os
import shutil
import tempfile

from conan_ci.artifactory import Artifactory
from conan_ci.tools import chdir, run_command


class BuildPackageJob(object):

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
        run_command('conan remote add upload_remote {}'.format(self.repo_read.url))
        run_command('conan remote add central_remote {}'.format(self.repo_upload.url))

        # Download the lock file to the install folder
        self.repo_meta.download_node_lock(self.project_lock_remote_path, build_folder)
        run_command("conan graph clean-modified {}".format(build_folder))
        run_command('conan remove "*" -f')

        # Build the ref using the lockfile
        run_command("conan install {} --install-folder {} "
                    "--use-lock --build {}".format(self.ref, build_folder, self.ref))
        # self.repo_meta.store_install_log(self.results_remote_path, output.decode())

        # Upload the packages
        run_command('conan upload {} --all -r upload_remote'.format(self.ref))

        # Upload the modified lockfile to the right location
        self.repo_meta.store_node_lock(build_folder, self.results_remote_path)
        print("\n\n\n------------------------------------------------------")


class MainJob(object):

    def __init__(self, ci_adapter, ci_caller):

        self.ci_adapter = ci_adapter
        self.ci_caller = ci_caller

        art_url = os.getenv("ARTIFACTORY_URL")
        art_user = os.getenv("ARTIFACTORY_USER")
        art_password = os.getenv("ARTIFACTORY_PASSWORD")

        current_slug = ci_adapter.get_key("slug")
        pr_number = ci_adapter.get_key("pr_number")
        commit = ci_adapter.get_key("commit")
        dest_branch = ci_adapter.get_key("dest_branch")
        build_number = ci_adapter.get_key("build_number")

        art = Artifactory(art_url, art_user, art_password)

        self.build_unique_id = "{}_PR{}_{}_{}".format(current_slug.replace("/", "_"), pr_number,
                                                      commit, build_number)
        self.repo_read = art.create_repo(self.build_unique_id)
        self.repo_upload = art.get_repo(dest_branch)
        self.repo_meta = art.get_meta()

        self.checkout_folder = os.getcwd()

    def run(self):


        try:
            run_command('conan remote remove conan-center')
        except Exception:
            pass
        run_command('conan remote add upload_remote {}'.format(self.repo_read.url))
        run_command('conan remote add central_remote {}'.format(self.repo_upload.url))

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
                run_command("conan create {} {} "
                            "--install-folder {} "
                            "--use-lock".format(self.checkout_folder, ref, install_folder))
                run_command('conan upload {} --all -r upload_remote'.format(ref))

                # Get the build order for that lock
                groups = self.get_build_order(install_folder)

                # Update and clean main lock
                self.update_lockfile(project_ref, profile_name, install_folder)

                # Remote lock file path
                project_lock_path = self.repo_meta.project_lock_path(self.build_unique_id,
                                                                     project_ref,
                                                                     profile_name)
                for group in groups:
                    group_pids = []
                    # Build the nodes
                    for node_id, ref in group:
                        print("Buildeo {}".format(ref))
                        ref = ref.split(":")[0].split("#")[0]
                        remote_results_path = self.repo_meta.node_lock_path(self.build_unique_id,
                                                                            project_ref,
                                                                            profile_name, ref,
                                                                            node_id)

                        pid = self.ci_caller.call_build(node_id, ref, project_lock_path,
                                                        remote_results_path, self.repo_read.name,
                                                        self.repo_upload.name)
                        group_pids.append(pid)

                    self.ci_caller.wait(group_pids)

                    for node_id, ref in group:
                        # Get the generated lockfile
                        ref = ref.split(":")[0].split("#")[0]
                        remote_results_path = self.repo_meta.node_lock_path(self.build_unique_id,
                                                                            project_ref,
                                                                            profile_name, ref,
                                                                            node_id)
                        tmp_path = tempfile.mkdtemp()
                        self.repo_meta.download_node_lock(remote_results_path, tmp_path)

                        # Update and clean main lock
                        self.update_lockfile(project_ref, profile_name, tmp_path)
                        shutil.rmtree(tmp_path)

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
            run_command('conan graph build-order . --json {}'.format(json_path))
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

