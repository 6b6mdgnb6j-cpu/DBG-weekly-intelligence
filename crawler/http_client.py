import logging
import re
import time

import requests


HEADERS = {"User-Agent": "Mozilla/5.0 weekly-report-contact"}

DEFAULT_TIMEOUT = (8, 25)
DEFAULT_ATTEMPTS = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
NO_RETRY_STATUS_CODES = {400, 401, 403, 404, 410}
TRANSIENT_SSL_PATTERNS = (
    "unexpected eof",
    "unexpected_eof",
    "eof occurred",
    "connection reset",
    "remote end closed connection",
    "tlsv1 alert internal error",
)
CERTIFICATE_SSL_PATTERNS = (
    "certificate_verify_failed",
    "certificate verify failed",
    "hostname",
    "self-signed certificate",
    "unable to get local issuer certificate",
    "certifi",
)

LOGGER = logging.getLogger("weekly_report.http_client")
SESSION = requests.Session()


def _timeout_value(timeout):
    return DEFAULT_TIMEOUT if timeout is None else timeout


def _attempt_count(attempts=None, max_attempts=None):
    value = max_attempts if max_attempts is not None else attempts
    if value is None:
        value = DEFAULT_ATTEMPTS
    return max(1, int(value))


def _retry_after_seconds(response):
    header = response.headers.get("Retry-After", "") if response is not None else ""
    if not header:
        return None
    if re.fullmatch(r"\d+", header.strip()):
        return min(float(header), 2.0)
    return None


def _backoff_seconds(attempt_index, response=None):
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        return retry_after
    return min(0.5 * (2 ** max(0, attempt_index - 1)), 2.0)


def _ssl_error_type(exc):
    text = str(exc).lower()
    if any(pattern in text for pattern in CERTIFICATE_SSL_PATTERNS):
        return "ssl_certificate_error"
    if any(pattern in text for pattern in TRANSIENT_SSL_PATTERNS):
        return "transient_ssl_error"
    return "ssl_error"


def _exception_retryable(exc, retry_transient_ssl=True):
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return True, "timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        error_type = _ssl_error_type(exc)
        return bool(retry_transient_ssl and error_type == "transient_ssl_error"), error_type
    if isinstance(exc, requests.exceptions.ConnectionError):
        return True, "connection_error"
    if isinstance(exc, (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema, requests.exceptions.MissingSchema)):
        return False, "invalid_url"
    return False, exc.__class__.__name__


def _annotate_result(obj, metadata):
    for key, value in metadata.items():
        setattr(obj, f"network_{key}", value)
    return obj


def _record_meta(meta, outcome):
    if meta is None or outcome is None:
        return
    attempts = int(getattr(outcome, "network_attempts", 1) or 1)
    meta["requests_total"] = int(meta.get("requests_total") or 0) + 1
    meta["request_attempts_total"] = int(meta.get("request_attempts_total") or 0) + attempts
    if getattr(outcome, "network_retried", False):
        meta["retried_requests"] = int(meta.get("retried_requests") or 0) + 1
        retry_reasons = getattr(outcome, "network_retry_reasons", []) or []
        if retry_reasons:
            meta["last_retry_error"] = retry_reasons[-1]
    status_code = getattr(outcome, "network_final_status_code", None)
    if status_code:
        meta["last_status_code"] = int(status_code)
    error_type = getattr(outcome, "network_final_error_type", "")
    if error_type:
        meta["last_request_error"] = error_type


def _finish_response(response, metadata, meta):
    response = _annotate_result(response, metadata)
    _record_meta(meta, response)
    if (response.encoding or "").lower() in ("iso-8859-1", "windows-1252"):
        response.encoding = response.apparent_encoding
    return response


def _finish_error(exc, metadata, meta):
    exc = _annotate_result(exc, metadata)
    _record_meta(meta, exc)
    raise exc


def request(
    method,
    url,
    *,
    headers=None,
    timeout=None,
    attempts=None,
    max_attempts=None,
    params=None,
    data=None,
    json=None,
    retry_post=False,
    retry_transient_ssl=True,
    meta=None,
):
    method = method.upper()
    total_attempts = _attempt_count(attempts=attempts, max_attempts=max_attempts)
    retry_method = method in {"GET", "HEAD"} or (method == "POST" and retry_post)
    retry_reasons = []
    start_time = time.monotonic()
    last_exc = None

    for attempt in range(1, total_attempts + 1):
        try:
            response = SESSION.request(
                method,
                url,
                headers=headers or HEADERS,
                timeout=_timeout_value(timeout),
                params=params,
                data=data,
                json=json,
            )
            status_code = response.status_code
            retryable_status = (
                retry_method
                and status_code in RETRY_STATUS_CODES
                and attempt < total_attempts
            )
            if retryable_status:
                retry_reasons.append(f"status:{status_code}")
                delay = _backoff_seconds(attempt, response)
                LOGGER.warning(
                    "request failed attempt %s/%s: %s %s status=%s; retrying in %.1fs",
                    attempt,
                    total_attempts,
                    method,
                    url,
                    status_code,
                    delay,
                )
                time.sleep(delay)
                continue

            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                metadata = {
                    "attempts": attempt,
                    "retried": bool(retry_reasons),
                    "final_status_code": status_code,
                    "final_error_type": f"http_{status_code}",
                    "elapsed_time": round(time.monotonic() - start_time, 3),
                    "retry_reasons": retry_reasons,
                }
                return _finish_error(exc, metadata, meta)

            metadata = {
                "attempts": attempt,
                "retried": bool(retry_reasons),
                "final_status_code": status_code,
                "final_error_type": "",
                "elapsed_time": round(time.monotonic() - start_time, 3),
                "retry_reasons": retry_reasons,
            }
            if retry_reasons:
                LOGGER.warning(
                    "request succeeded attempt %s/%s: %s %s",
                    attempt,
                    total_attempts,
                    method,
                    url,
                )
            return _finish_response(response, metadata, meta)
        except Exception as exc:
            if hasattr(exc, "network_attempts"):
                raise
            last_exc = exc
            retryable_exc, error_type = _exception_retryable(exc, retry_transient_ssl=retry_transient_ssl)
            should_retry = retry_method and retryable_exc and attempt < total_attempts
            if not should_retry:
                metadata = {
                    "attempts": attempt,
                    "retried": bool(retry_reasons),
                    "final_status_code": getattr(getattr(exc, "response", None), "status_code", None),
                    "final_error_type": error_type,
                    "elapsed_time": round(time.monotonic() - start_time, 3),
                    "retry_reasons": retry_reasons,
                }
                return _finish_error(exc, metadata, meta)
            retry_reasons.append(error_type)
            delay = _backoff_seconds(attempt)
            LOGGER.warning(
                "request failed attempt %s/%s: %s %s error=%s; retrying in %.1fs",
                attempt,
                total_attempts,
                method,
                url,
                error_type,
                delay,
            )
            time.sleep(delay)

    metadata = {
        "attempts": total_attempts,
        "retried": bool(retry_reasons),
        "final_status_code": None,
        "final_error_type": last_exc.__class__.__name__ if last_exc else "unknown",
        "elapsed_time": round(time.monotonic() - start_time, 3),
        "retry_reasons": retry_reasons,
    }
    return _finish_error(last_exc, metadata, meta)


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)
