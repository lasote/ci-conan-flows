import json
import os
import re

import time

from conan_ci.artifactory import Artifactory
from conan_ci.model.build_create_info import BuildCreateInfo
from conan_ci.model.node_info import NodeInfo
from conan_ci.runner import docker_runner, regular_runner
from conan_ci.tools import load, environment_append, cur_folder


class ConanCreateJob(object):
    """To build a single node using a lockfile"""

    def __init__(self):

        art_url = os.environ["ARTIFACTORY_URL"]
        art_user = os.environ["ARTIFACTORY_USER"]
        art_password = os.environ["ARTIFACTORY_PASSWORD"]
        art = Artifactory(art_url, art_user, art_password)

        data = json.loads(os.environ["CONAN_CI_BUILD_JSON"])
        self.info = BuildCreateInfo.loads(art, data)

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

    @staticmethod
    def get_built_node_id(lock_folder)-> NodeInfo:
        data = load(os.path.join(lock_folder, "conan.lock"))
        data = json.loads(data)
        for node_id, doc in data["graph_lock"]["nodes"].items():
            if "modified" in doc and doc["modified"]:
                return NodeInfo(node_id, doc["pref"])
        return None

    def run(self):
        # Home at the current dir
        with environment_append({"CONAN_USER_HOME": cur_folder()}):
            conan_home = os.path.join(cur_folder(), ".conan")
            os.makedirs(conan_home)
            with open(os.path.join(conan_home, "artifacts.properties"), "w") as fh:
                fh.write("artifact_property_build.name={}\n"
                         "artifact_property_build.number={}\n"
                         "artifact_property_build.timestamp={}".format(self.info.build.name,
                                                                       self.info.build.number,
                                                                       time.time()))

            print("\n------------------------------------------------------")
            print(" CREATE JOB: '{}' AT '{}'".format(self.info.node_info.ref, cur_folder()))
            print("-----------------------------------------------------\n")
            build_folder = cur_folder()

            # Download the lock file to the install folder
            self.info.repos.meta.download_project_lock(build_folder, self.info.build,
                                                       self.info.build_conf)

            docker_image = self.get_docker_image_from_lockfile(build_folder)
            rcm = docker_runner(docker_image, [build_folder]) if docker_image else regular_runner()

            with rcm as runner:
                if docker_image:  # FIXME: Issue locally
                    runner.run("git clone https://github.com/conan-io/conan.git")
                    try:
                        runner.run("pip uninstall -y conan-package-tools")
                    except:
                        pass
                    runner.run("cd conan && git checkout develop")
                    runner.run("cd conan && pip install -e .")
                try:
                    runner.run('conan remote remove conan-center')
                except Exception:
                    pass
                runner.run('conan --version')
                runner.run('conan config set general.default_package_id_mode=package_revision_mode')
                runner.run('conan remote add upload_remote {}'.format(self.info.repos.write.url))
                runner.run('conan user -r upload_remote -p')
                if self.info.repos.write.url != self.info.repos.read.url:
                    runner.run('conan remote add central_remote {}'.format(self.info.repos.read.url))
                    runner.run('conan user -r central_remote -p')
                runner.run('conan remove "*" -f')

                # Build the ref using the lockfile
                cmd = "conan install {} --lockfile={} " \
                      "--build {} --install-folder={}".format(self.info.node_info.ref,
                                                              build_folder,
                                                              self.info.node_info.ref,
                                                              build_folder)
                try:
                    output = runner.run(cmd)
                    print("Package built at: {}".format(build_folder))
                    print(output)
                except Exception as exc:
                    self.info.repos.meta.store_install_log(str(exc), self.info.build,
                                                           self.info.build_conf,
                                                           self.info.node_info)
                    self.info.repos.meta.store_failure(self.info.build,
                                                       self.info.build_conf,
                                                       self.info.node_info)
                    raise exc
                self.info.repos.meta.store_install_log(output, self.info.build,
                                                       self.info.build_conf,
                                                       self.info.node_info)

                if self.info.logger:
                    node_info = self.get_built_node_id(build_folder)
                    self.info.logger.add_node_stopped_building(node_info)

                # Upload the packageshttps://api.myjson.com/bins/15mvo5
                runner.run('conan upload {} --all -r '
                           'upload_remote --force'.format(self.info.node_info.ref))
                # Upload the modified lockfile to the right location
                # Here the location for the current node will have "modified": "Build"
                self.info.repos.meta.store_node_lock(build_folder,
                                                     self.info.build,
                                                     self.info.build_conf,
                                                     self.info.node_info)
                self.info.repos.meta.store_success(self.info.build,
                                                   self.info.build_conf,
                                                   self.info.node_info)
