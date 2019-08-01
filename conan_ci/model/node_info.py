
class NodeInfo(object):

    def __init__(self, node_id, ref):
        self.id = node_id
        self.ref = ref

    def dumps(self):
        return {"id": self.id,
                "ref": self.ref}

    @staticmethod
    def loads(data):
        return NodeInfo(data["id"], data["ref"])

