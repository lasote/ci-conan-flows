import json

from conan_ci.artifactory import Artifactory
from conan_ci.model.build import Build
from conan_ci.tools import load, iso_now


def get_remote_path_from_ref(pref):
    tmp = pref.split("#", 1)
    ref = tmp[0]
    tmp = tmp[1].split(":", 1)
    rrev = tmp[0]
    tmp = ref.split("@", 1)
    name, version = tmp[0].split("/")
    user, channel = tmp[1].split("/")
    return "{}/{}/{}/{}/{}".format(user, name, version, channel, rrev)


def get_remote_path_from_pref(pref):
    """
    "AA/1.0@conan/stable#3628c47a7d11086e9b149010c15df762:0ab9fcf606068d4347207cc29edd400ceccbc944#caca9466b49d1302b07d78b0367005b1"
    =>
    conan/AA/1.0/stable/3628c47a7d11086e9b149010c15df762/package/0ab9fcf606068d4347207cc29edd400ceccbc944/caca9466b49d1302b07d78b0367005b1
    """
    tmp = pref.split("#", 1)
    tmp = tmp[1].split(":", 1)
    tmp = tmp[1].split("#", 1)
    package_id = tmp[0]
    prev = tmp[1]

    path_ref = get_remote_path_from_ref(pref)
    return "{}/package/{}/{}".format(path_ref, package_id, prev)


def _not_repeated(sha1, a_list):
    for el in a_list:
        if el.get("sha1") == sha1:
            return False
    return True


def get_module_id(pref):
    # Ref without revisions
    return pref.split("#")[0]


class BuildInfoBuilder(object):

    art: Artifactory

    def __init__(self, art: Artifactory):
        self.modules = {}
        self.art = art
        self.started = iso_now()

    def get_build_info(self, build: Build):
        ret = {"version": "1.0.1",
               "name": build.name,
               "number": build.number,
               "started": self.started,
               "buildAgent": {"name": "Conan Client", "version": "1.X"},
               "modules": list(self.modules.values())}
        return ret

    def _get_files_of_package(self, pref):
        path = get_remote_path_from_pref(pref)
        return self.art.get_files_of_path(path)

    def _get_files_of_recipe(self, pref):
        path = "{}/export".format(get_remote_path_from_ref(pref))
        return self.art.get_files_of_path(path)

    def _get_artifacts(self, pref, include_recipe=True):
        ret = self._get_files_of_package(pref)
        if include_recipe:
            ret.extend(self._get_files_of_recipe(pref))
        return ret

    def _merge_modules(self, modules):

        for mod_id, mod in modules.items():
            if mod_id not in self.modules:
                self.modules[mod_id] = mod
            else:
                for artifact in mod["artifacts"]:
                    if _not_repeated(artifact["sha1"], self.modules[mod_id]["artifacts"]):
                        self.modules[mod_id]["artifacts"].append(artifact)
                for artifact in mod["dependencies"]:
                    if _not_repeated(artifact["sha1"], self.modules[mod_id]["dependencies"]):
                        self.modules[mod_id]["dependencies"].append(artifact)

    def process_lockfile(self, lockfile_path):
        contents = load(lockfile_path)
        bi_modules = {}
        data = json.loads(contents)

        # First iteration, create the modules
        for node_id, node in data["graph_lock"]["nodes"].items():
            if node.get("modified"):
                pref = node["pref"]
                # This node has been created
                module = {"id": get_module_id(pref),
                          "artifacts": self._get_artifacts(pref),
                          "dependencies": []}
                bi_modules[module["id"]] = module

        # Second iteration, build the dependencies
        for node_id, node in data["graph_lock"]["nodes"].items():
            if not node.get("modified"):
                pref = node["pref"]
                for require_ref in node.get("requires", []):
                    module_id = get_module_id(require_ref)
                    if module_id in bi_modules:
                        bi_modules[module_id]["dependencies"] = self._get_artifacts(pref)

        self._merge_modules(bi_modules)


if __name__ == "__main__":
    arti_url = "http://localhost:8090/artifactory"
    arti_user = "admin"
    arti_password = "password"
    art = Artifactory(arti_url, arti_user, arti_password)

    builder = BuildInfoBuilder(art)
    builder.process_lockfile("ss")
    builder.process_lockfile("ss")
    builder.process_lockfile("ss")
    bi = builder.get_build_info(Build("My_build", "23"))
    print(bi)
