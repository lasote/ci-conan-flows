
class BuildConfiguration(object):

    def __init__(self, project_ref: str, profile_name: str):
        self.project_ref = project_ref
        self.profile_name = profile_name

    def dumps(self):
        return {"project_ref": self.project_ref,
                "profile_name": self.profile_name}

    @staticmethod
    def loads(data):
        return BuildConfiguration(data["project_ref"], data["profile_name"])
