"""Application-level exceptions."""


class FatalError(Exception):
    """Unrecoverable problem that stops the application."""


class ReservationError(Exception):
    """Reserving a particular slot failed; searching can continue."""


class CenterNotAllowedError(ReservationError):
    """The service rejects reservations at this exam center for the user's PKK profile."""

    def __init__(self, center_id: int, message: str):
        super().__init__(message)
        self.center_id = center_id
