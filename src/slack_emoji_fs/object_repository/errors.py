class ObjectRepositoryError(Exception):
    pass

class InvalidNamespaceError(ObjectRepositoryError):
    pass

class InvalidObjectIdError(ObjectRepositoryError):
    pass

class ObjectNotFoundError(ObjectRepositoryError):
    pass

class CorruptObjectError(ObjectRepositoryError):
    pass

class WrongObjectTypeError(ObjectRepositoryError):
    pass