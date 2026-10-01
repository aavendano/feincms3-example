import pytest

from feincms3_filecontent.exceptions import ConfigurationError, ProviderError
from feincms3_filecontent.providers.bitbucket import BitbucketProvider
from feincms3_filecontent.providers.github import GitHubProvider
from feincms3_filecontent.providers.gitlab import GitLabProvider


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout):
        self.calls.append((method, url, headers, payload))
        return self.responses.pop(0)


GH_PR = {
    "number": 7,
    "html_url": "https://github.com/o/r/pull/7",
    "state": "open",
    "title": "Update about",
    "head": {"ref": "content/update-about"},
    "base": {"ref": "main"},
}


def test_token_comes_from_environment(monkeypatch):
    monkeypatch.delenv("FC_TOKEN", raising=False)
    with pytest.raises(ConfigurationError):
        GitHubProvider(repository="o/r", token_env="FC_TOKEN")
    monkeypatch.setenv("FC_TOKEN", "s3cret")
    provider = GitHubProvider(repository="o/r", token_env="FC_TOKEN")
    assert "s3cret" not in repr(provider)


def test_github():
    transport = Transport(
        (201, GH_PR),
        (200, {**GH_PR, "merged": True}),
        (200, [{"user": {"login": "x"}, "state": "APPROVED"}]),
        (200, [GH_PR]),
        (200, {"state": "success"}),
        (405, {"message": "Pull Request is not mergeable"}),
    )
    gh = GitHubProvider(repository="o/r", token="t", transport=transport)
    pr = gh.create_pull_request(
        head="content/update-about", base="main", title="Update about"
    )
    assert (pr.number, pr.state, pr.head) == (7, "open", "content/update-about")
    method, url, headers, payload = transport.calls[0]
    assert (method, url) == ("POST", "https://api.github.com/repos/o/r/pulls")
    assert headers["Authorization"] == "Bearer t"
    assert payload["head"] == "content/update-about"

    pr = gh.get_pull_request(7)
    assert (pr.state, pr.review_state) == ("merged", "approved")
    assert gh.find_pull_request(head="content/update-about", base="main").number == 7
    assert "head=o%3Acontent%2Fupdate-about" in transport.calls[3][1]
    assert gh.get_status("main") == "success"
    with pytest.raises(ProviderError, match="HTTP 405"):
        gh.merge_pull_request(7)


def test_gitlab():
    mr = {
        "iid": 3,
        "web_url": "https://gitlab.com/g/p/-/merge_requests/3",
        "state": "opened",
        "title": "T",
        "source_branch": "content/x",
        "target_branch": "main",
    }
    transport = Transport((201, mr), (200, {**mr, "state": "merged"}), (200, []))
    gl = GitLabProvider(project="g/p", token="t", transport=transport)
    assert (
        gl.create_pull_request(head="content/x", base="main", title="T").state == "open"
    )
    assert (
        transport.calls[0][1]
        == "https://gitlab.com/api/v4/projects/g%2Fp/merge_requests"
    )
    assert transport.calls[0][2]["PRIVATE-TOKEN"] == "t"
    assert gl.merge_pull_request(3).state == "merged"
    assert gl.find_pull_request(head="content/x", base="main") is None


def test_bitbucket():
    pr = {
        "id": 5,
        "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/5"}},
        "state": "OPEN",
        "title": "T",
        "source": {"branch": {"name": "content/x"}},
        "destination": {"branch": {"name": "main"}},
        "participants": [{"approved": True}],
    }
    transport = Transport((201, pr), (200, {"values": [{"state": "INPROGRESS"}]}))
    bb = BitbucketProvider(repository="w/r", token="t", transport=transport)
    created = bb.create_pull_request(head="content/x", base="main", title="T")
    assert (created.number, created.review_state) == (5, "approved")
    assert transport.calls[0][3]["destination"] == {"branch": {"name": "main"}}
    assert bb.get_status("abc") == "pending"
