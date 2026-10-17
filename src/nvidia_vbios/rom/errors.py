"""Versioned errors shared by the offline ROM and editor APIs."""

class VbiosError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else details

    def to_dict(self):
        return {'schema_version': 1, 'error': {'code': self.code,
                'message': str(self), 'details': self.details}}


class FormatError(VbiosError):
    def __init__(self, message, *, details=None):
        super().__init__('UNSUPPORTED_FORMAT', message, details=details)
