"""SDK/framework-independent failures shared by adapters, use cases, and HTTP handlers."""


class PersistenceUnavailableError(Exception):
    """A persistence operation could not complete; no absence may be inferred."""


class PersistenceDataError(Exception):
    """Stored data cannot be reconstructed as a valid document job."""


class UploadValidationError(Exception):
    """Upload metadata violates the configured upload policy."""


class UploadAuthorizationUnavailableError(Exception):
    """Upload signing could not complete; no authorization should be returned."""
