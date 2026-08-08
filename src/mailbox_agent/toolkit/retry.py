"""Retry/backoff for external API calls (Gmail, Drive, Telegram).

Without this, one transient 429/500 - which happens routinely under normal
Gmail API quota pressure - crashes an entire scheduled sort or sweep run
instead of just that one call.

Retrying is not free of risk, though: it's only safe to blindly retry a call
that's idempotent (repeating it has the same effect as doing it once). This
module intentionally exposes two decorators instead of one:

- `retry_read`: GET/LIST calls. Always safe - re-fetching data has no side
  effects.
- `retry_idempotent_write`: writes that are safe to repeat (adding a label
  that's already applied, trashing an already-trashed message).

Calls that are genuinely NOT safe to blindly retry - the Drive backup
upload, most importantly, where a network blip after the write actually
succeeded could create a duplicate backup file - are deliberately left
undecorated. See the comment at the call site in drive.py.
"""

import requests
from googleapiclient.errors import HttpError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        return status in _RETRYABLE_HTTP_STATUSES
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response is not None and exc.response.status_code in _RETRYABLE_HTTP_STATUSES
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def _backoff_retry(max_attempts: int):
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )


retry_read = _backoff_retry(max_attempts=5)
retry_idempotent_write = _backoff_retry(max_attempts=3)
