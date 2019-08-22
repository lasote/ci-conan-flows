import os
import tempfile

import fasteners
import requests

from conan_ci.model.build import Build
from conan_ci.model.build_configuration import BuildConfiguration
from conan_ci.model.node_info import NodeInfo


class JsonLogger(object):

    def __init__(self, url=None):
        self.url = url or self.get_new_doc()
        print("******************* JSON URL *******************************")
        print(self.url)
        self.lock_path = os.path.join(tempfile.mkdtemp(), ".conan_ci.lock")

    @staticmethod
    def get_new_doc():
        ret = requests.post("https://api.myjson.com/bins", json={"elements": []})
        if not ret.ok:
            raise Exception("Cannot create json remote")
        return ret.json()["uri"]

    def push_doc(self, doc):
        # I'm doing this because with processes it collides between the read and the write
        with fasteners.InterProcessLock(self.lock_path, logger=None):
            ret = requests.get(self.url)
            if not ret.ok:
                raise Exception("Cannot read json remote")
            data = ret.json()
            data["elements"].append(doc)
            ret = requests.put(self.url, json=data)
            if not ret.ok:
                raise Exception("Cannot update json remote")

    def add_graph(self, build: Build, build_conf: BuildConfiguration, graph):
        doc = {"action": "push_graph",
               "data": {"name": "{}#{} - {} - {}".format(build.name,
                                                         build.number,
                                                         build_conf.project_ref,
                                                         build_conf.profile_name,
                                                         ), "graph": graph}}
        self.push_doc(doc)

    def add_node_building(self, node_info: NodeInfo):
        doc = {"action": "node_building", "data": {"node": node_info.id,
                                                   "pref": node_info.ref}}
        self.push_doc(doc)

    def add_node_stopped_building(self, node_info: NodeInfo):
        doc = {"action": "node_stopped_building", "data": {"node": node_info.id,
                                                           "pref": node_info.ref}}
        print("LLAMADO STOP BUILDING!!! {}".format(node_info.id))
        self.push_doc(doc)
