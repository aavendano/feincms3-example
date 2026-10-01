from urllib.parse import quote

from .base import GitProvider, PullRequest


class GitHubProvider(GitProvider):
    """
    ``OPTIONS = {"repository": "owner/name", "token_env": "GITHUB_TOKEN"}``

    Set ``api_url`` for GitHub Enterprise (``https://host/api/v3``).
    """

    api_url = "https://api.github.com"

    def __init__(self, *, repository, **kwargs):
        super().__init__(**kwargs)
        self.owner, self.name = repository.split("/", 1)

    def headers(self):
        return {
            **super().headers(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def _repo(self):
        return f"/repos/{quote(self.owner)}/{quote(self.name)}"

    def _pr(self, data, review_state=""):
        state = (
            "merged" if data.get("merged") or data.get("merged_at") else data["state"]
        )
        return PullRequest(
            number=data["number"],
            url=data["html_url"],
            state=state,
            title=data["title"],
            head=data["head"]["ref"],
            base=data["base"]["ref"],
            review_state=review_state,
            raw=data,
        )

    def create_pull_request(self, *, head, base, title, body=""):
        data = self.request(
            "POST",
            f"{self._repo}/pulls",
            {"head": head, "base": base, "title": title, "body": body},
        )
        return self._pr(data)

    def get_pull_request(self, number):
        data = self.request("GET", f"{self._repo}/pulls/{int(number)}")
        reviews = self.request("GET", f"{self._repo}/pulls/{int(number)}/reviews")
        return self._pr(data, self._review_state(reviews))

    def find_pull_request(self, *, head, base):
        head_ref = quote(f"{self.owner}:{head}", safe="")
        data = self.request(
            "GET", f"{self._repo}/pulls?state=open&head={head_ref}&base={quote(base)}"
        )
        return self._pr(data[0]) if data else None

    def merge_pull_request(self, number, *, method="merge"):
        self.request(
            "PUT", f"{self._repo}/pulls/{int(number)}/merge", {"merge_method": method}
        )
        return self.get_pull_request(number)

    def get_status(self, ref):
        data = self.request("GET", f"{self._repo}/commits/{quote(ref, safe='')}/status")
        return data.get("state", "")

    @staticmethod
    def _review_state(reviews):
        latest = {}
        for review in reviews or ():
            latest[review["user"]["login"]] = review["state"]
        states = set(latest.values())
        if "CHANGES_REQUESTED" in states:
            return "changes_requested"
        if "APPROVED" in states:
            return "approved"
        return "pending"
