import json
import os
import tempfile
from typing import Dict, List

import requests
from rtpy import Rtpy, rtpy
from rtpy.artifacts_and_storage import RtpyArtifactsAndStorage
from rtpy.tools import RtpyBase

from conan_ci.model.build import Build
from conan_ci.model.build_configuration import BuildConfiguration
from conan_ci.model.node_info import NodeInfo


class ArtifactoryRepo(object):

    af: Rtpy
    name: str
    af_store: RtpyArtifactsAndStorage

    def __init__(self, base_url, name, af: Rtpy):
        self.url = "{}/api/conan/{}".format(base_url, name)
        self.af = af
        self.name = name
        self.af_store = self.af.artifacts_and_storage

    def get_artifactory(self):
        return Artifactory(self.af.settings.get("af_url"),
                           self.af.settings.get("username"),
                           self.af.settings.get("password"))

    def list_files(self, folder: str):
        tmp = self.af_store.file_list(self.name, folder, options="&listFolders=0")
        return [t["uri"][1:] for t in tmp["files"]]

    def mkdir(self, folder):
        self.af_store.create_directory(self.name, folder)

    def as_meta(self):
        return MetaRepo(self.url, self.name, self.af)

    def read_file(self, path):
        try:
            return self.af.artifacts_and_storage.retrieve_artifact(self.name, path).content
        except self.af.MalformedAfApiError as error:
            print(self.name)
            print(path)
            print(dir(error))
            print(error.response)
            print("\n\n".join(getattr(error, attr) for attr in dir(error)))
            raise

    def download_file(self, path, dest_folder):
        profile_contents = self.read_file(path)
        p_path = "/".join([dest_folder, os.path.basename(path)])
        with open(p_path, "wb") as f:
            f.write(profile_contents)
        return p_path

    def deploy(self, path, dest_path):
        self.af_store.deploy_artifact(self.name, path, dest_path)

    def deploy_contents(self, dest_path, contents):
        tmp = tempfile.mkdtemp()
        file_path = os.path.join(tmp, "file")
        with open(file_path, "w") as fl:
            fl.write(contents)
        self.af_store.deploy_artifact(self.name, file_path, dest_path)

    def set_properties(self, props: Dict[str, List], path=None):
        path = path or "/"
        self.af_store.set_item_properties(self.name, path, ";".join(["{}={}".format(k, ",".join(v))
                                                                    for k, v in props.items()]))

    def get_properties(self, path=None) -> Dict[str, List]:
        path = path or "/"
        r = self.af_store.item_properties(self.name, path)
        return r["properties"]

    def remove(self):
        self.af.repositories.delete_repository(self.name)

    def copy_all_to_repo(self, dest_repo_name):
        retries = 4
        for _ in range(retries):
            try:
                self.af_store.copy_item(self.name, "/", dest_repo_name, "/")
                return
            except:
                pass

    def refresh_index(self):
        settings = self.af.settings
        ret = requests.post(settings["af_url"] + "/api/conan/{}/reindex".format(self.name),
                            auth=(settings["username"], settings["password"]))
        if not ret.ok:
            raise Exception("Error refreshing the index of repository {}".format(self.name))


class MetaRepo(ArtifactoryRepo):

    @staticmethod
    def _project_lock_path(build: Build, build_conf: BuildConfiguration):
        project_ref = build_conf.project_ref.replace("/", "_").replace("@", "_")
        return "lockfiles/{}/{}/{}/{}".format(build.name, build.number, project_ref,
                                              build_conf.profile_name)

    @staticmethod
    def _node_lock_path(build: Build, build_conf: BuildConfiguration, node_info: NodeInfo):
        ref = node_info.ref.replace("/", "_").replace("@", "_")
        tmp = MetaRepo._project_lock_path(build, build_conf)
        return "{}/{}_{}".format(tmp, ref, node_info.id)

    def store_last_repo_lock(self, name: str, local_lock_path: str, profile_name):
        path = "lockfiles/{}/{}".format(name, profile_name)
        try:
            props = self.get_properties(path)
        except:
            counter = 0
            self.mkdir(path)
        else:
            counter = int(props.get("last_lock_counter", ["1"])[0])

        counter += 1
        self.set_properties({"last_lock_counter": ["{}".format(counter)]}, path)
        self.deploy("/".join([local_lock_path, "conan.lock"]),
                    "/".join([path, "{}_conan.lock".format(counter)]))

        # Override also the latest
        self.deploy("/".join([local_lock_path, "conan.lock"]),
                    "/".join([path, "latest_conan.lock"]))

    def store_node_lock(self, path: str, build: Build,
                        build_conf: BuildConfiguration, node_conf: NodeInfo):
        remote_path = self._node_lock_path(build, build_conf, node_conf)
        print("Uploading lockfile to: {}".format(remote_path))
        self.deploy("/".join([path, "conan.lock"]),
                    "/".join([remote_path, "conan.lock"]))

    def store_project_lock(self, path: str, build: Build, build_conf: BuildConfiguration):
        remote_path = self._project_lock_path(build, build_conf)
        print("Uploading lockfile to: {}".format(remote_path))
        self.deploy("/".join([path, "conan.lock"]),
                    "/".join([remote_path, "conan.lock"]))

    def store_install_log(self, log: str, build: Build, build_conf: BuildConfiguration,
                          node_conf: NodeInfo):
        remote_path = self._node_lock_path(build, build_conf, node_conf)
        self.deploy_contents("/".join([remote_path, "install.log"]), log)

    def store_failure(self, build: Build, build_conf: BuildConfiguration,
                      node_conf: NodeInfo):
        remote_path = self._node_lock_path(build, build_conf, node_conf)
        self.deploy_contents("/".join([remote_path, "FAILED"]), "")

    def store_success(self, build: Build, build_conf: BuildConfiguration,
                      node_conf: NodeInfo):
        remote_path = self._node_lock_path(build, build_conf, node_conf)
        self.deploy_contents("/".join([remote_path, "OK"]), "")

    def get_status(self, build: Build, build_conf: BuildConfiguration, node_conf: NodeInfo):
        try:
            remote_path = self._node_lock_path(build, build_conf, node_conf)
            self.read_file("/".join([remote_path, "OK"]))
            return True
        except Exception:
            return False

    def get_log(self, build: Build, build_conf: BuildConfiguration, node_conf: NodeInfo):
        remote_path = self._node_lock_path(build, build_conf, node_conf)
        return self.read_file("/".join([remote_path, "install.log"]))

    def download_node_lock(self, path: str, build: Build, build_conf: BuildConfiguration,
                           node_info: NodeInfo):

        remote_lock_path = self._node_lock_path(build, build_conf, node_info)
        print("Downloading lockfile from: {}".format(remote_lock_path))

        remote_path = "/".join([remote_lock_path, "conan.lock"])
        self.download_file(remote_path, path)

    def download_project_lock(self, path: str, build: Build, build_conf: BuildConfiguration):

        remote_lock_path = self._project_lock_path(build, build_conf)
        print("Downloading lockfile from: {}".format(remote_lock_path))

        remote_path = "/".join([remote_lock_path, "conan.lock"])
        self.download_file(remote_path, path)

    def get_profile_names(self):
        return self.list_files("profiles")

    def get_projects_refs(self):
        p = self.read_file("config.json")
        projects_ref = json.loads(p)["projects"]
        return projects_ref

    def download_profile(self, profile_name, dest_folder):
        return self.download_file("profiles/{}".format(profile_name), dest_folder)

    def store_build_pr_association(self, build: Build, current_slug, pr_number):
        remote_path = "info_pr/{}/{}/build.json".format(current_slug, pr_number)
        self.deploy_contents(remote_path, json.dumps(build.dumps()))

    def get_build_from_pr(self, current_slug, pr_number):
        remote_path = "info_pr/{}/{}/build.json".format(current_slug, pr_number)
        tmp = self.read_file(remote_path)
        data = json.loads(tmp)
        return Build.loads(data)


class Artifactory(object):

    af: Rtpy
    url: str

    def __init__(self, artifactory_url: str, username: str, password: str):
        self.url = artifactory_url
        settings = {"af_url": artifactory_url, "username": username, "password": password}
        self.af = Rtpy(settings)
        self.af.system_and_configuration.system_health_ping()

    def create_repo(self, name: str) -> ArtifactoryRepo:
        params = {"key": name, "rclass": "local", "packageType": "conan"}
        self.af.repositories.create_repository(params)
        return ArtifactoryRepo(self.url, name, self.af)

    def get_repo(self, name: str):
        return ArtifactoryRepo(self.url, name, self.af)

    def list_repos(self):
        tmp = self.af.repositories.get_repositories()
        return [ArtifactoryRepo(r["url"], r["key"], self.af) for r in tmp]

    def get_files_of_path(self, path):

        def _not_repeated(sha1, a_list):
            for ell in a_list:
                if ell.get("sha1") == sha1:
                    return False
            return True

        q = 'items.find({"path": "%s"})' \
            '.include("repo", "name", "path", "actual_md5", "actual_sha1")' % path

        ret_data = self.af.searches.artifactory_query_language(q)

        ret = []
        for res in ret_data["results"]:
            if res["name"] in [".timestamp"]:
                continue
            if _not_repeated(res["actual_sha1"], ret):
                el = {"sha1": res["actual_sha1"], "md5": res["actual_md5"], "name": res["name"]}
                ret.append(el)
        return ret

    def publish_build_info(self, bi):
        # Not implemented in the library
        self.af.builds._request("PUT", "build", "Publish build info", kwargs={},
                                params={"Content-Type": "application/json"}, data=json.dumps(bi))

    def promote_build(self, build: Build, source_repo: ArtifactoryRepo,
                      dest_repo: ArtifactoryRepo):
        # Not implemented in the library
        data = {"status": "merged",
                "ciUser": "builder",
                "dryRun": False,
                "sourceRepo": source_repo.name,
                "targetRepo": dest_repo.name,
                "copy": True,
                "artifacts": True,
                "dependencies": False,
                "failFast": False}
        # failFast is set to True because otherwise it fails. I assume it could be related with
        # some artifacts already promoted (recipes not changing) or something like that.
        # Similar to: https://www.jfrog.com/jira/browse/RTFACT-12087
        try:
            self.af.builds._request("POST",
                                    "build/promote/{}/{}".format(build.name, build.number),
                                    "Promote build info", kwargs={},
                                    params={"Content-Type": "application/json"},
                                    data=json.dumps(data))
        except RtpyBase.AfApiError as exc:
            print("WARN: No packages promoted!")
            if exc.status_code == 400:  # Empty build info
                return
            raise
        except Exception as e:
            print(e)
            raise
