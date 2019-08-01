import json
import os
import re
import shutil
import tempfile
from typing import List

import time

from conan_ci.artifactory import Artifactory
from conan_ci.build_info import BuildInfoBuilder
from conan_ci.json_logger import JsonLogger
from conan_ci.model.build import Build
from conan_ci.model.build_configuration import BuildConfiguration
from conan_ci.model.build_create_info import BuildCreateInfo
from conan_ci.model.node_info import NodeInfo
from conan_ci.model.repos_build import ReposBuild
from conan_ci.runner import run
from conan_ci.tools import environment_append, cur_folder, load
from conan_ci.tools import tmp_folder


def get_pull_request_from_message(commit_message):
    node_regex = re.compile(r'.*#(\d+).*')
    ret = node_regex.match(commit_message)
    if not ret:
        return None
    return ret.group(1)


def unique_pr_id(slug, pr_number):
    tmp = slug.split("/")[1]  # Removing the user from the slug, use it if needed
    return "{}-pr-{}".format(tmp, pr_number)


def unique_build_id(slug, dest_branch, build_number):
    return "{}_{}_{}".format(slug.replace("/", "_"), dest_branch, build_number)


class CoordinatorJob(object):
    """To attend a PR or a regular build of a branch"""
    logger: JsonLogger
    repos: ReposBuild
    art: Artifactory

    def __init__(self, ci_adapter, ci_caller, logger: JsonLogger, repos: ReposBuild):

        self.logger = logger
        self.ci_adapter = ci_adapter
        self.ci_caller = ci_caller

        self.repos = repos
        self.art = self.repos.meta.get_artifactory()

    def run(self):
        # Home at the current dir
        with environment_append({"CONAN_USER_HOME": cur_folder()}):
            is_pr = True
            try:
                self.ci_adapter.get_key("pr_number")
            except KeyError:
                is_pr = False

            if not is_pr:
                message = self.ci_adapter.get_key("commit_message")
                pr_number = get_pull_request_from_message(message)
                if pr_number:
                    self.run_merge(pr_number)

                self.run_job()
            else:
                self.run_pr()

    def run_pr(self):
        current_slug = self.ci_adapter.get_key("slug")
        pr_number = self.ci_adapter.get_key("pr_number")
        # commit = self.ci_adapter.get_key("commit")

        build = Build(unique_pr_id(current_slug, pr_number),
                      self.ci_adapter.get_key("build_number"))

        dest_branch = self.ci_adapter.get_key("dest_branch")
        # ANY dest branch uses the same "dev" and "pre-dev" repositories
        # Abrir un PR a master quiere decir que es la ultima build de la version que se esta "congelando"
        # por tanto no hay problema, será pues la ultima revision del paquete.

        self.repos.meta.store_build_pr_association(build, current_slug, pr_number)

        job = NodeChain(build, self.repos, self.ci_caller, self.logger)
        job.run()

    def run_merge(self, pr_number):
        dest_branch = self.ci_adapter.get_key("dest_branch")
        build_number = self.ci_adapter.get_key("build_number")
        current_slug = self.ci_adapter.get_key("slug")
        print("Merging {}:{} to {}".format(pr_number, build_number, dest_branch))

        # Copy the packages to the other repo
        build = self.repos.meta.get_build_from_pr(current_slug, pr_number)
        self.art.promote_build(build, self.repos.write, self.repos.read)
        self.repos.read.refresh_index()

    def run_job(self):
        """Regular job, push to develop for example"""
        current_slug = self.ci_adapter.get_key("slug")
        build_number = self.ci_adapter.get_key("build_number")
        dest_branch = self.ci_adapter.get_key("dest_branch")
        build_name = unique_build_id(current_slug, dest_branch, build_number)

        build = Build(build_name, build_number)
        repos = ReposBuild(self.repos.read, self.repos.read, self.repos.meta)

        job = NodeChain(build, repos, self.ci_caller, self.logger)
        job.run()

        # Store the lockfiles for the build
        #with tmp_folder() as t:
        #    profiles_names = self.repos.meta.get_profile_names()
        #    projects_refs = self.repos.meta.get_projects_refs()
        #    for project_ref in projects_refs:
        #        for profile_name in profiles_names:
        #            repos.meta.download_node_lock(t)
        #            repos.meta.store_last_repo_lock(self.dev_repo_name, t, profile_name)


class NodeChain(object):

    build: Build
    repos: ReposBuild
    art: Artifactory

    def __init__(self, build: Build, repos: ReposBuild, ci_caller, logger):
        self.ci_caller = ci_caller
        self.repos = repos
        self.checkout_folder = cur_folder()
        self._launched_nodes_ids = []
        self.logger = logger
        self.build = build
        self.art = repos.read.get_artifactory()

    @staticmethod
    def _pref_to_ref(pref):
        return NodeChain._pref_to_ref_with_rrev(pref).split("#")[0]

    @staticmethod
    def _pref_to_ref_with_rrev(pref):
        return pref.split(":")[0]

    def _call_build(self, build_conf: BuildConfiguration, node_info: NodeInfo):
        self.logger.add_node_building(node_info)
        self._launched_nodes_ids.append(node_info.id)
        create_info = BuildCreateInfo(self.build, build_conf, node_info, self.repos, self.logger)
        self.ci_caller.call_build(create_info)

    def _export_and_queue_modified_node(self, project_ref, profile_name):

        with tmp_folder() as tmp_path:
            # Generate and upload the lock file for the project
            profile_path = self.repos.meta.download_profile(profile_name, tmp_path)
            run("conan graph lock {} --profile {}".format(project_ref, profile_path))
            print("LOCK DESPUES DE CONAN GRAPH LOCK")
            self.print_lock(tmp_path)

            # Get the reference of the node being modified
            # The lockfile is modified with the new RREV
            name, version = self.inspect_name_and_version(self.checkout_folder)
            reference = "{}/{}@conan/stable".format(name, version)
            run("conan export {} {} --lockfile {}".format(self.checkout_folder, reference,
                                                          tmp_path))

            print("LOCK DESPUES DE EXPORT")
            self.print_lock(tmp_path)

            run('conan upload {} -r upload_remote'.format(reference))

            data = load(os.path.join(tmp_path, "conan.lock"))
            self.logger.add_graph(self.build, json.loads(data))

            # Get the nodes corresponding to the ref being modified
            # And queue all of them if they have been modified (no modified => FF)
            to_launch = self._get_first_group_to_build(tmp_path)
            build_conf = BuildConfiguration(project_ref, profile_name)
            self.repos.meta.store_project_lock(tmp_path, self.build, build_conf)
            for new_node_id, new_pref in to_launch:
                new_ref = self._pref_to_ref(new_pref)
                print("::::::: Launching {} ({}) at the start"
                      " because it is missing".format(new_ref, profile_name, new_ref))
                node_info = NodeInfo(new_node_id, new_ref)
                self._call_build(build_conf, node_info)

    @staticmethod
    def print_lock(lock_folder):
        print(load(os.path.join(lock_folder, "conan.lock")))

    def process_ended_nodes(self, project_ref):
        # print("Checking ended jobs...")
        ended: List[BuildCreateInfo] = self.ci_caller.check_ended()

        # Update the project lock files by merging the lock from all the ended jobs
        for build_create_info in ended:
            # Clear generated packages
            run('conan remove "*" -f')

            print("Processing ended job: {}-{}".format(build_create_info.node_info.ref,
                                                       build_create_info.build_conf.profile_name))
            # Check status
            status = self.repos.meta.get_status(build_create_info.build,
                                                build_create_info.build_conf,
                                                build_create_info.node_info)
            if not status:
                try:
                    log = self.repos.meta.get_log(build_create_info.build,
                                                  build_create_info.build_conf,
                                                  build_create_info.node_info)
                except Exception:
                    log = "No log generated"
                raise Exception("The job '{}:{}' failed with "
                                "error: {}".format(build_create_info.node_info.ref,
                                                   build_create_info.build_conf.profile_name, log))

            # Download the node lockfile
            node_lock_folder = tempfile.mkdtemp()
            project_lock_folder = tempfile.mkdtemp()

            self.repos.meta.download_project_lock(project_lock_folder,
                                                  build_create_info.build,
                                                  build_create_info.build_conf)
            self.repos.meta.download_node_lock(node_lock_folder,
                                               build_create_info.build,
                                               build_create_info.build_conf,
                                               build_create_info.node_info)

            # Update the project lock with the node lock and upload it
            run("conan graph update-lock {} {}".format(project_lock_folder, node_lock_folder))
            self.repos.meta.store_node_lock(project_lock_folder,
                                            build_create_info.build,
                                            build_create_info.build_conf,
                                            build_create_info.node_info)

            # Get new build order to iterate the new available nodes
            # the cascade could be replaced with a RREV default mode for example
            to_launch = self._get_first_group_to_build(project_lock_folder)
            # The build-order can modify the graph with the resolved nodes, so store it
            self.repos.meta.store_project_lock(project_lock_folder, self.build,
                                               build_create_info.build_conf)
            for new_node_id, new_pref in to_launch:
                new_ref = self._pref_to_ref(new_pref)
                print("::::::: Launching {} ({}) "
                      "after {} ended".format(new_ref, build_create_info.build_conf.profile_name,
                                              build_create_info.node_info.ref))
                build_conf = BuildConfiguration(project_ref,
                                                build_create_info.build_conf.profile_name)
                node_info = NodeInfo(new_node_id, new_ref)
                self._call_build(build_conf, node_info)

            shutil.rmtree(node_lock_folder)
            shutil.rmtree(project_lock_folder)

    def _get_first_group_to_build(self, project_lock_folder):

        run('conan graph build-order "{}" --json bo.json -b missing'.format(project_lock_folder))
        with open("bo.json") as f:
            groups = json.load(f)
        ret = []
        if groups:
            first_group = groups[0]
            for new_node_id, new_pref in first_group:
                if new_node_id in self._launched_nodes_ids:
                    print(":::::: Skipping already launched node: {}".format(new_pref))
                else:
                    ret.append([new_node_id, new_pref])

        print("Lock despues de build-order")
        self.print_lock(project_lock_folder)
        print("First group: {}".format(ret))
        return ret

    def run(self):
        builder = BuildInfoBuilder(self.art)

        run('conan config set general.default_package_id_mode=package_revision_mode')
        run('conan remote remove conan-center', ignore_failure=True)
        run('conan remote add upload_remote {}'.format(self.repos.write.url))
        run('conan user -r upload_remote -p')
        if self.repos.read.url != self.repos.write.url:
            # Is the same remote when push to develop for example
            run('conan remote add central_remote {}'.format(self.repos.read.url))
            run('conan user -r central_remote -p')

        profiles_names = self.repos.meta.get_profile_names()
        projects_refs = self.repos.meta.get_projects_refs()
        # TODO: We should do here the same than c3i, infos to calculate
        #  different package id?
        #  conan info <ref> -if=<path_to_lock> --use-lock --json
        for project_ref in projects_refs:
            for profile_name in profiles_names:
                self._export_and_queue_modified_node(project_ref, profile_name)
                # Clear generated packages
                run('conan remove "*" -f')

            # While there are jobs pending for the project...
            print("Waiting for all jobs to be completed...")
            while not self.ci_caller.empty_queue():
                self.process_ended_nodes(project_ref)
                delay_secs = int(os.getenv("CONAN_CI_CHECK_DELAY_SECONDS", "3"))
                # Do not consume api calls limit checking
                time.sleep(delay_secs)

            # CALCULATE THE BUILD INFO
            print("All jobs of the project completed!")
            for profile_name in profiles_names:
                with tmp_folder() as tmp_path:
                    build_conf = BuildConfiguration(project_ref, profile_name)
                    self.repos.meta.download_project_lock(tmp_path, self.build, build_conf)
                    builder.process_lockfile(os.path.join(tmp_path, "conan.lock"))

            bi = builder.get_build_info(self.build)
            print(bi)
            self.art.publish_build_info(bi)

    @staticmethod
    def inspect_name_and_version(folder):
        json_path = os.path.join(folder, "nv.json")
        run("conan inspect {} -a name -a version --json {}".format(folder, json_path))
        with open(json_path) as f:
            c = f.read()
        os.unlink(json_path)
        data = json.loads(c)
        installed = data["name"]
        version = data["version"]
        return installed, version
