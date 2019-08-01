
class Build(object):

    def __init__(self, build_name, build_number):
        self.name = build_name
        self.number = build_number

    def dumps(self):
        return {"name": self.name,
                "number": self.number}

    @staticmethod
    def loads(data):
        return Build(data["name"], data["number"])

