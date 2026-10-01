"""
Optional hosting-provider adapters (pull requests, review status, merge).

The core never depends on a provider: plain Git is enough for direct mode and
for pushing review branches. Tokens are read from an environment variable
(``token_env``) so they never end up in settings files, documents or commits.
"""

import abc
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..exceptions import ConfigurationError, ProviderError


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    state: str  # "open", "closed", "merged"
    title: str
    head: str
    base: str
    review_state: str = ""  # "approved", "changes_requested", "pending", ""
    raw: dict = field(default_factory=dict, repr=False, compare=False)


def urllib_transport(method, url, headers, payload, timeout):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode() or "null"
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"message": body}


class GitProvider(abc.ABC):
    api_url = ""

    def __init__(
        self, *, token=None, token_env=None, api_url=None, timeout=30, transport=None
    ):
        if token is None and token_env:
            token = os.environ.get(token_env)
        if not token:
            raise ConfigurationError(
                f"{type(self).__name__} needs a token; set the {token_env or 'token'} "
                "environment variable."
            )
        self._token = token
        self.api_url = (api_url or self.api_url).rstrip("/")
        self.timeout = timeout
        self.transport = transport or urllib_transport

    def __repr__(self):
        # Never leak the token through repr()/logging.
        return f"<{type(self).__name__} {self.api_url}>"

    def headers(self):
        return {"Accept": "application/json", "Authorization": f"Bearer {self._token}"}

    def request(self, method, path, payload=None, *, expected=(200, 201)):
        url = f"{self.api_url}{path}"
        status, data = self.transport(
            method, url, self.headers(), payload, self.timeout
        )
        if status not in expected:
            message = data.get("message") if isinstance(data, dict) else data
            raise ProviderError(f"{method} {path} failed with HTTP {status}: {message}")
        return data

    @abc.abstractmethod
    def create_pull_request(self, *, head, base, title, body="") -> PullRequest: ...

    @abc.abstractmethod
    def get_pull_request(self, number) -> PullRequest: ...

    @abc.abstractmethod
    def find_pull_request(self, *, head, base) -> PullRequest | None: ...

    @abc.abstractmethod
    def merge_pull_request(self, number, *, method="merge") -> PullRequest: ...

    @abc.abstractmethod
    def get_status(self, ref) -> str:
        """Combined CI status of ``ref``: "success", "pending", "failure" or ""."""
