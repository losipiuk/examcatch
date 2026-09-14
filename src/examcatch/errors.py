"""Application-level exceptions."""


class FatalError(Exception):
    """Unrecoverable problem that stops the application."""


class ReservationError(Exception):
    """Reserving a particular slot failed; searching can continue."""
