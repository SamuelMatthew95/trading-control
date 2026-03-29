"""
Simple FakeSession and FakeResult for async testing compatibility.
"""


class FakeResult:
    def __init__(self, value=None):
        self._value = value

    def scalar(self):
        return self._value


class FakeSession:
    def __init__(self, result=None):
        self.result = FakeResult(result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def begin(self):
        return self

    async def execute(self, stmt):
        return self.result
