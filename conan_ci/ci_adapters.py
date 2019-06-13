import os


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

    def __init__(self):
        raise NotImplementedError("Still not implemented, look at "
                                  "https://github.com/lasote/build_node")
