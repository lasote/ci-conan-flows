import json
import os
import tempfile
from typing import Dict, List

from rtpy import Rtpy
from rtpy.artifacts_and_storage import RtpyArtifactsAndStorage


class ArtifactoryRepo(object):

    af: Rtpy
    name: str
    af_store: RtpyArtifactsAndStorage

    def __init__(self, base_url, name, af: Rtpy):
        self.url = "{}/api/conan/{}".format(base_url, name)
        self.af = af
        self.name = name
        self.af_store = self.af.artifacts_and_storage

    def list_files(self, folder: str):
        tmp = self.af_store.file_list(self.name, folder, options="&listFolders=0")
        return [t["uri"][1:] for t in tmp["files"]]

    def read_file(self, path):
        return self.af.artifacts_and_storage.retrieve_artifact(self.name, path).content

    def download_file(self, path, dest_folder):
        profile_contents = self.read_file(path)
        p_path = os.path.join(dest_folder, os.path.basename(path))
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

    def set_properties(self, props: Dict[str, List]):
        self.af_store.set_item_properties(self.name, "/", ";".join(["{}={}".format(k, ",".join(v))
                                                                    for k, v in props.items()]))

    def get_properties(self) -> Dict[str, List]:
        r = self.af_store.item_properties(self.name, "/")
        return r["properties"]

    def remove(self):
        self.af.repositories.delete_repository(self.name)


class MetaRepo(ArtifactoryRepo):
    name: str = "meta"

    @staticmethod
    def project_lock_path(build_unique_id: str, ref: str, profile_name: str):
        ref = ref.replace("/", "_").replace("@", "_")
        return "tmp/{}/{}/{}".format(build_unique_id, ref, profile_name)

    @staticmethod
    def node_lock_path(build_unique_id: str, project_ref: str, profile_name: str,
                       ref: str, node_id: str):
        ref = ref.replace("/", "_").replace("@", "_")
        tmp = MetaRepo.project_lock_path(build_unique_id, project_ref, profile_name)
        return "{}/{}_{}".format(tmp, ref, node_id)

    def store_node_lock(self, local_lock_path: str, remote_lock_path: str):
        self.deploy(os.path.join(local_lock_path, "conan.lock"),
                    os.path.join(remote_lock_path, "conan.lock"))

    def store_install_log(self, remote_lock_path: str, log: str):
        self.deploy_contents(os.path.join(remote_lock_path, "install.log"), log)

    def store_failure(self, remote_lock_path: str):
        self.deploy_contents(os.path.join(remote_lock_path, "FAILED"), "")

    def store_success(self, remote_lock_path: str):
        self.deploy_contents(os.path.join(remote_lock_path, "OK"), "")

    def get_status(self, remote_lock_path: str):
        try:
            self.read_file(os.path.join(remote_lock_path, "OK"))
            return True
        except Exception:
            return False

    def get_log(self, remote_lock_path):
        return self.read_file(os.path.join(remote_lock_path, "install.log"))

    def download_node_lock(self, remote_lock_path: str, dest_folder):
        remote_path = os.path.join(remote_lock_path, "conan.lock")
        self.download_file(remote_path, dest_folder)

    def get_profile_names(self):
        return self.list_files("profiles")

    def get_projects_refs(self):
        p = self.read_file("projects.json")
        projects_ref = json.loads(p)["projects"]
        return projects_ref

    def download_profile(self, profile_name, dest_folder):
        return self.download_file("profiles/{}".format(profile_name), dest_folder)


class Artifactory(object):

    af: Rtpy
    url: str

    def __init__(self, artifactory_url: str, username: str, password: str):
        self.url = artifactory_url
        settings = {"af_url": artifactory_url, "username": username, "password": password,
                    "raw_response": True}
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

    def get_meta(self):
        return MetaRepo(self.url, MetaRepo.name, self.af)
