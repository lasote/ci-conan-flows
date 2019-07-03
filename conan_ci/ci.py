import json
import os
import re
import shutil
import tempfile

import time

from conan_ci.artifactory import Artifactory
from conan_ci.runner import docker_runner, regular_runner, run
from conan_ci.tools import load, environment_append, \
    tmp_folder, run_command


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

    @staticmethod
    def get_docker_image_from_lockfile(folder):
        contents = load(os.path.join(folder, "conan.lock"))
        version_regex = re.compile(r'.*compiler\.version=(\d+\.*\d*)\\n.*', re.DOTALL)
        ret = version_regex.match(contents)
        if not ret:
            return None
        version = ret.group(1)

        if "compiler=gcc\\n" in contents:
            return "conanio/gcc{}".format(version)
        if "compiler=clang\\n" in contents:
            return "conanio/clang{}".format(version)
        return None

    def run(self):
        # Home at the current dir
        with environment_append({"CONAN_USER_HOME": cur_folder()}):
            print("\n\n\n------------------------------------------------------")
            print("BUILDING '{}' AT '{}'".format(self.ref, cur_folder()))
            build_folder = cur_folder()

            # Download the lock file to the install folder
            self.repo_meta.download_node_lock(self.project_lock_remote_path, build_folder)

            docker_image = self.get_docker_image_from_lockfile(build_folder)
            rcm = docker_runner(docker_image, [build_folder]) if docker_image else regular_runner()

            with rcm as runner:
                if docker_image:  # FIXME: Issue locally
                    runner.run("git clone https://github.com/memsharded/conan.git")
                    runner.run("cd conan && git checkout feature/lockfiles")
                    runner.run("cd conan && pip install -e .")
                runner.run("conan --version")
                try:
                    runner.run('conan remote remove conan-center')
                except Exception:
                    pass
                runner.run('conan remote add upload_remote {}'.format(self.repo_upload.url))
                runner.run('conan remote add central_remote {}'.format(self.repo_read.url))
                runner.run('conan user -r upload_remote -p')
                runner.run('conan user -r central_remote -p')
                runner.run("conan graph clean-modified {}".format(build_folder))
                runner.run('conan remove "*" -f')

                # Build the ref using the lockfile
                print("\n\n****************** INSTALL OUTPUT {} ************************"
                      "".format(self.ref))

                print("CONAN USER HOME: {}".format(os.getenv("CONAN_USER_HOME")))
                runner.run("conan --version")
                cmd = "conan install {} --lockfile={} " \
                      "--build {} --install-folder={}".format(self.ref, build_folder, self.ref,
                                                              build_folder)

                runner.run('cat {}/conan.lock'.format(build_folder))

                try:
                    output = runner.run(cmd, capture_output=True)
                    print("Package built at: {}".format(build_folder))
                    print(output)
                except Exception as exc:
                    self.repo_meta.store_install_log(self.results_remote_path, str(exc))
                    self.repo_meta.store_failure(self.results_remote_path)
                    raise exc

                print(output)
                print("************************************************************\n\n")

                self.repo_meta.store_install_log(self.results_remote_path, output)

                # Upload the packages
                runner.run('conan upload {} --all -r upload_remote'.format(self.ref))
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
        # Home at the current dir
        with environment_append({"CONAN_USER_HOME": cur_folder()}):
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
        current_slug = self.ci_adapter.get_key("slug")
        pr_number = self.ci_adapter.get_key("pr_number")
        commit = self.ci_adapter.get_key("commit")
        build_number = self.ci_adapter.get_key("build_number")
        build_unique_id = unique_repo_name(current_slug, pr_number, build_number, commit)
        dest_branch = self.ci_adapter.get_key("dest_branch")
        repo_read = self.art.get_repo(dest_branch)
        repo_upload = self.art.create_repo(build_unique_id)

        job = PRJob(self.art, self.ci_caller, build_unique_id, repo_read, repo_upload)
        job.run()

    def run_merge(self, pr_number):
        dest_branch = self.ci_adapter.get_key("dest_branch")
        print("Merging {} to {}".format(pr_number, dest_branch))

        # Get the right repository
        slug = self.ci_adapter.get_key("slug")

        ret = self.art.list_repos()
        latest = -1
        last_repo = None
        for r in ret:
            if r.name.startswith(unique_repo_name(slug, pr_number, "", "")[:-1]):
                build_time = float(r.get_properties()["build_time"][0])
                if build_time > latest:
                    last_repo = r

        # Copy the packages to the other repo
        last_repo.copy_all_to_repo(dest_branch)

        # Remove the origin repository
        last_repo.remove()

        # Repeat the build in develop
        self.run_job()

    def run_job(self):
        """Regular job, push to develop for example"""
        # For each project
        #   For each profile
        #      Graph info (will resolve latests revisions) and calculate the bins to build
        #         if it is a FF => won't be anything.d
        pass


def cur_folder():
    return os.getcwd().replace("\\", "/")


def unique_repo_name(slug, pr_number, build_number, commit):
    return "{}_PR{}_{}_{}".format(slug.replace("/", "_"), pr_number, build_number, commit)


class PRJob(object):

    def __init__(self, art, ci_caller, build_unique_id, repo_read, repo_upload):
        self.art = art
        self.ci_caller = ci_caller
        self.repo_meta = self.art.get_meta()
        self.repo_upload = repo_upload
        self.repo_read = repo_read

        self.build_unique_id = build_unique_id
        self.repo_upload.set_properties({"build_time": [str(time.time())]})
        self.checkout_folder = cur_folder()

    @staticmethod
    def _pref_to_ref(pref):
        return pref.split(":")[0].split("#")[0]

    def _call_build(self, project_ref, profile_name, node_id, reference):
        # Remote lock file path
        project_lock_path = self.repo_meta.project_lock_path(self.build_unique_id,
                                                             project_ref,
                                                             profile_name)
        remote_results_path = self.repo_meta.node_lock_path(self.build_unique_id,
                                                            project_ref,
                                                            profile_name, reference,
                                                            node_id)
        self.ci_caller.call_build(node_id, profile_name, reference,
                                  project_lock_path, remote_results_path,
                                  self.repo_read.name, self.repo_upload.name)

    def _export_and_queue_modified_node(self, project_ref, profile_name):

        with tmp_folder() as tmp_path:
            # Generate and upload the lock file for the project
            profile_path = self.repo_meta.download_profile(profile_name, tmp_path)
            run_command("conan graph lock {} --profile {}".format(project_ref, profile_path))
            remote_path_project = self.repo_meta.project_lock_path(self.build_unique_id,
                                                                   project_ref,
                                                                   profile_name)
            self.repo_meta.store_node_lock(tmp_path, remote_path_project)

            # Get the reference of the node being modified
            name, version = self.inspect_name_and_version(self.checkout_folder)
            reference = "{}/{}@conan/stable".format(name, version)
            run_command("conan export {} {} --lockfile {}".format(
                self.checkout_folder, reference, tmp_path))
            run_command('conan upload {} -r upload_remote'.format(reference))

            # Get the nodes corresponding to the ref being modified
            # And queue all the builds
            lock = json.loads(load("conan.lock"))["graph_lock"]
            for node_id, data in lock["nodes"].items():
                node_reference = self._pref_to_ref(data["pref"])
                if node_reference == reference:
                    self._call_build(project_ref, profile_name, node_id, reference)

    def process_ended_nodes(self, project_ref):
        print("Checking ended jobs...")
        ended = self.ci_caller.check_ended()
        for node_info in ended:
            # Clear generated packages
            run_command('conan remove "*" -f')

            print("Processing ended job: {}-{}".format(node_info.ref, node_info.profile_name))
            # Check status
            status = self.repo_meta.get_status(node_info.lock_path)
            if not status:
                try:
                    log = self.repo_meta.get_log(node_info.lock_path)
                except Exception:
                    log = "No log generated"
                raise Exception("The job '{}:{}' failed with "
                                "error: {}".format(node_info.ref, node_info.profile_name, log))
            node_lock_folder = tempfile.mkdtemp()
            project_lock_folder = tempfile.mkdtemp()

            # Download the node lockfile
            self.repo_meta.download_node_lock(node_info.lock_path, node_lock_folder)

            # Download the project lock
            project_lock_remote = self.repo_meta.project_lock_path(self.build_unique_id,
                                                                   project_ref,
                                                                   node_info.profile_name)
            self.repo_meta.download_node_lock(project_lock_remote, project_lock_folder)

            # Update the project lock with the node lock
            run_command("conan graph update-lock {} {}".format(project_lock_folder,
                                                               node_lock_folder))

            # Store again the project lock
            self.repo_meta.store_node_lock(project_lock_folder, project_lock_remote)

            # Get new build order to iterate the new available nodes
            # the cascade could be replaced with a RREV default mode for example
            run_command('conan graph build-order "{}" --json bo.json --build cascade'
                        ''.format(project_lock_folder))
            with open("bo.json") as f:
                groups = json.load(f)

            if groups:
                first_group = groups[0]
                for new_node_id, new_pref in first_group:
                    new_ref = self._pref_to_ref(new_pref)
                    self._call_build(project_ref, node_info.profile_name, new_node_id, new_ref)

            shutil.rmtree(node_lock_folder)
            shutil.rmtree(project_lock_folder)

    def run(self):

        try:
            run('conan remote remove conan-center')
        except Exception:
            pass
        run('conan remote add upload_remote {}'.format(self.repo_upload.url))
        run('conan remote add central_remote {}'.format(self.repo_read.url))
        run('conan user -r upload_remote -p')
        run('conan user -r central_remote -p')

        profiles_names = self.repo_meta.get_profile_names()
        projects_refs = self.repo_meta.get_projects_refs()
        # TODO: We should do here the same than c3i, infos to calculate
        #  different package id?
        #  conan info <ref> -if=<path_to_lock> --use-lock --json
        for project_ref in projects_refs:
            for profile_name in profiles_names:
                self._export_and_queue_modified_node(project_ref, profile_name)
                # Clear generated packages
                run_command('conan remove "*" -f')

            # While there are jobs pending for the project...
            while not self.ci_caller.empty_queue():
                self.process_ended_nodes(project_ref)
                delay_secs = int(os.getenv("CONAN_CI_CHECK_DELAY_SECONDS", "3"))
                # Do not consume api calls limit checking
                print("\n\nSleeping {} secs...".format(delay_secs))
                time.sleep(delay_secs)

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
