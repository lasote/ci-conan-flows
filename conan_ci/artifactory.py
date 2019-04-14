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

    def deploy_contents(self, contents, dest_path):
        tmp = tempfile.mkdtemp()
        filepath = os.path.join(tmp, "file")
        with open(filepath, "w") as f:
            f.write(contents)
        self.af_store.deploy_artifact(self.name, filepath, dest_path)

    def set_properties(self, props: Dict[str, List]):
        self.af_store.set_item_properties(self.name, "/", ";".join(["{}={}".format(k, ",".join(v))
                                                                    for k, v in props.items()]))

    def get_properties(self) -> Dict[str, List]:
        r = self.af_store.item_properties(self.name, "/")
        return r["properties"]

    def remove(self):
        self.af.repositories.delete_repository(self.name)


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



if __name__ == "__main__":
    a = Artifactory("http://localhost:8090/artifactory", "admin", "password")
    t = tempfile.mkdtemp()
    f_path = os.path.join(t, "file.txt")
    with open(f_path, "w") as f:
        f.write("contents")
    repo = a.get_repo("hey")
    repo.deploy(f_path, "kk/de/la/vk/file.txt")
    print(repo.list_files("kk/de/la/vk"))
    repo.set_properties({"cosa": ["buena", "mane"], "mierda": ["fina"]})
    print(repo.get_properties()["cosa"])
