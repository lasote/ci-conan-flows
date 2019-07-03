import os
import uuid
from contextlib import contextmanager

from conan_ci.tools import run_command_output


def run(command, capture_output=False) -> str:
    output = ""
    if not capture_output:
        ret = os.system(command)
        if ret != 0:
            raise Exception()
    else:
        try:
            output = run_command_output(command)
        except Exception as exc:
            raise Exception("Error: {}.\n Output: {}".format(exc, output))
    return output


class CommandRunner(object):

    @staticmethod
    def run(command, capture_output=False):
        return run(command, capture_output)


class DockerCommandRunner(object):

    _docker_image: str
    _container_id: str

    def __init__(self, docker_image, *mount_dirs):
        self._docker_image = docker_image
        self._mount_dirs = mount_dirs or []
        self._container_id = uuid.uuid4()
        super(DockerCommandRunner, self).__init__()

    def container_start(self):
        volumes_line = " ".join(["-v {}:{}".format(f, f) for f in self._mount_dirs])
        env_var_line = " ".join(["-e {}".format(env_name) for env_name in os.environ.keys()
                                 if env_name.startswith("CONAN")])
        cmd = "docker run {} {} --network host -td " \
              "--name {} {} /bin/bash".format(env_var_line, volumes_line, self._container_id,
                                              self._docker_image)
        run(cmd)

    def container_stop(self):
        run("docker stop {}".format(self._container_id))
        run("docker rm {}".format(self._container_id))

    def run(self, command, capture_output=False):
        mixed = 'docker container exec {} sh -c "{}"'.format(self._container_id, command)
        print(mixed)
        output = run(mixed, capture_output)
        return output


@contextmanager
def docker_runner(image_name, mount_dirs):
    rn = DockerCommandRunner(image_name, *mount_dirs)
    try:
        rn.container_start()
        yield rn
    finally:
        rn.container_stop()


@contextmanager
def regular_runner():
    yield CommandRunner()
