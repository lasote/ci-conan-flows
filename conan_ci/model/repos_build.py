

class ReposBuild(object):
    from conan_ci.artifactory import ArtifactoryRepo, Artifactory, MetaRepo

    read: ArtifactoryRepo
    write: ArtifactoryRepo
    meta: MetaRepo

    def __init__(self, read: ArtifactoryRepo, write: ArtifactoryRepo, meta: MetaRepo):
        self.read = read
        self.write = write
        self.meta = meta

    def dumps(self):
        return {"read": self.read.name,
                "write": self.write.name,
                "meta": self.meta.name}

    @staticmethod
    def loads(art: Artifactory, data):
        return ReposBuild(art.get_repo(data["read"]), art.get_repo(data["write"]),
                          art.get_repo(data["meta"]).as_meta())

