from conan_ci.json_logger import JsonLogger
from conan_ci.model.build import Build
from conan_ci.model.build_configuration import BuildConfiguration
from conan_ci.model.node_info import NodeInfo
from conan_ci.model.repos_build import ReposBuild


class BuildCreateInfo(object):
    from conan_ci.artifactory import Artifactory

    build: Build
    build_conf: BuildConfiguration
    node_info: NodeInfo
    repos: ReposBuild
    logger: JsonLogger

    def __init__(self, build, build_conf, node_info, repos, logger):
        self.build = build
        self.build_conf = build_conf
        self.node_info = node_info
        self.repos = repos
        self.logger = logger

        self.running_id = None  # This is for storing the ID of the process or any other ID

    def dumps(self):
        ret = {"build": self.build.dumps(),
               "build_conf": self.build_conf.dumps(),
               "node_info": self.node_info.dumps(),
               "repos": self.repos.dumps(),
               "logger_url": self.logger.url}
        return ret

    @staticmethod
    def loads(art: Artifactory, data):
        ret = BuildCreateInfo(Build.loads(data["build"]),
                              BuildConfiguration.loads(data["build_conf"]),
                              NodeInfo.loads(data["node_info"]),
                              ReposBuild.loads(art, data["repos"]),
                              JsonLogger(data["logger_url"]))
        return ret
