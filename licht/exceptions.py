class LichtError(Exception):
    pass


class LichtTimeoutError(LichtError):
    def __init__(self, message=None):
        if message is None:
            message = 'an operation timed out'
        super().__init__(message)
