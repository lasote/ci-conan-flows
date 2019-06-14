import os
from collections import namedtuple
from typing import Dict
import requests

NodeBuilding = namedtuple("NodeBuilding", "node_id ref lock_path element")


class TravisCIAdapter(object):

    data = {"slug": "TRAVIS_REPO_SLUG",
            "pr_number": "TRAVIS_PULL_REQUEST",
            "commit": "TRAVIS_COMMIT",
            "dest_branch": "TRAVIS_BRANCH",
            "build_number": "TRAVIS_BUILD_NUMBER",
            "commit_message": "TRAVIS_COMMIT_MESSAGE"}

    def get_key(self, key):
        return os.environ[self.data[key]]


class TravisAPICaller(object):
    _run_processes: Dict[str, NodeBuilding]
    _end_processes: Dict[str, NodeBuilding]

    def __init__(self, travis, repo_slug, travis_token):
        self.travis = travis
        self._run_processes = {}
        self._end_processes = {}
        self.repo_slug = repo_slug.replace("/", "%2F")
        self.travis_token = travis_token

    def _repeated_node_id(self, node_id):
        for d in [self._run_processes, self._end_processes]:
            for _, process_id in d.items():
                if process_id.node_id == node_id:
                    return True
        return False

    def call_build(self, node_id: str, ref: str,
                   project_lock_path: str, remote_results_path: str,
                   read_remote_name: str, upload_remote_name: str):

        if self._repeated_node_id(node_id):
            print("Already launched: {}".format(node_id))
            return

        env = {"CONAN_CI_NODE_ID": node_id,
               "CONAN_CI_REFERENCE": ref,
               "CONAN_CI_READ_REMOTE_NAME": read_remote_name,
               "CONAN_CI_UPLOAD_REMOTE_NAME": upload_remote_name,
               "CONAN_CI_PROJECT_LOCK_PATH": project_lock_path,
               "CONAN_CI_REMOTE_RESULTS_PATH": remote_results_path}

        env_str = " ".join(["{}={}".format(k, v) for k, v in env.items()])
        data = {
             "request": {
                 "message": "Build for {}".format(ref),
                 "branch": "master",
                 "merge_mode": "merge",
                 "config": {
                    "env": [env_str],
                    "import": [{"source": "./linux.yml", "mode": "merge"}]
                 }
               }
            }

        ret = requests.post("https://api.travis-ci.org/repo/{}/requests".format(self.repo_slug),
                            headers=self._auth_headers(), json=data)
        if ret.ok:
            data_response = ret.json()
            request_id = data_response["request"]["id"]
            self._run_processes[request_id] = NodeBuilding(node_id, ref, remote_results_path, request_id)
        else:
            raise Exception(ret)

    def _auth_headers(self):
        headers = {"Authorization": "token {}".format(self.travis_token),
                   "Travis-API-Version": "3",
                   "content-type": "application/json"}
        return headers

    def check_ended(self):

        ret = requests.get("https://api.travis-ci.org/repo/{}/"
                           "requests".format(self.repo_slug),
                           headers=self._auth_headers())
        if not ret.ok:
            raise Exception("Error checking status: {}".format(ret))
        data = ret.json()
        node_infos = []
        for request in data["requests"]:
            request_id = request["id"]
            if request_id not in self._run_processes:
                continue
            builds = request.get("builds")
            if builds:
                build = builds[0]
                if build["state"] in ["failed", "cancelled", "errored", "passed"]:
                    self._end_processes[request_id] = self._run_processes[request_id]
                    del self._run_processes[request_id]
                    node_infos.append(self._end_processes[request_id])
        return node_infos

    def empty_queue(self):
        return len(self._run_processes) == 0



