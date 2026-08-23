class ObjectStoreError(Exception):
    pass

class ObjectAlreadyExistsError(ObjectStoreError):
    pass

class ObjectTooLargeError(ObjectStoreError):
    pass

class ObjectStoreUnavailableError(ObjectStoreError):
    pass