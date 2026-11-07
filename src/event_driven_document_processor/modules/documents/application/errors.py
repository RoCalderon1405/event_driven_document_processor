"""Storage-independent failures shared by persistence adapters and HTTP handlers."""


class PersistenceUnavailableError(Exception):
    """A persistence operation could not complete; no absence may be inferred."""


class PersistenceDataError(Exception):
    """Stored data cannot be reconstructed as a valid document job."""
