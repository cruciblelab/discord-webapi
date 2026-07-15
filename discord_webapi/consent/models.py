from datetime import datetime

from pydantic import BaseModel


class ConsentRecord(BaseModel):
    """Records that a user acknowledged a cookie/privacy notice.

    This library never renders or dictates the notice's text, styling, or
    which cookies it covers — that's entirely up to the consumer's own
    dashboard frontend. All this provides is a place to durably record that
    consent was given (and which version of the notice they saw), purely
    because some deployments are legally required to keep that record.
    Off by default (`enable_cookie_consent=False`); nothing reads or writes
    this unless a consumer opts in.
    """

    user_id: int
    consent_version: str
    given_at: datetime
