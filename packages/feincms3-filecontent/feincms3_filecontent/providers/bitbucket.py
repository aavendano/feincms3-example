from urllib.parse import quote

from .base import GitProvider, PullRequest


class BitbucketProvider(GitProvider):
    """``OPTIONS = {"repository": "workspace/slug", "token_env": "BITBUCKET_TOKEN"}``"""

    api_url = "https://api.bitbucket.org/2.0"

    def __init__(self, *, repository, **kwargs):
        super().__init__(**kwargs)
        self.workspace, self.slug = repository.split("/", 1)

    @property
    def _repo(self):
        return f"/repositories/{quote(self.workspace)}/{quote(self.slug)}"

    def _pr(self, data):
        state = {"OPEN": "open", "MERGED": "merged"}.get(data["state"], "closed")
        approved = any(p.get("approved") for p in data.get("participants", ()))
        return PullRequest(
            number=data["id"],
            url=data["links"]["html"]["href"],
            state=state,
            title=data["title"],
            head=data["source"]["branch"]["name"],
            base=data["destination"]["branch"]["name"],
            review_state="approved" if approved else "",
            raw=data,
        )

    def create_pull_request(self, *, head, base, title, body=""):
        data = self.request(
            "POST",
            f"{self._repo}/pullrequests",
            {
                "title": title,
                "description": body,
                "source": {"branch": {"name": head}},
                "destination": {"branch": {"name": base}},
            },
        )
        return self._pr(data)

    def get_pull_request(self, number):
        return self._pr(self.request("GET", f"{self._repo}/pullrequests/{int(number)}"))

    def find_pull_request(self, *, head, base):
        query = quote(
            f'state="OPEN" AND source.branch.name="{head}" AND destination.branch.name="{base}"',
            safe="",
        )
        data = self.request("GET", f"{self._repo}/pullrequests?q={query}")
        values = data.get("values", [])
        return self._pr(values[0]) if values else None

    def merge_pull_request(self, number, *, method="merge"):
        strategy = {
            "merge": "merge_commit",
            "squash": "squash",
            "rebase": "fast_forward",
        }
        data = self.request(
            "POST",
            f"{self._repo}/pullrequests/{int(number)}/merge",
            {"merge_strategy": strategy.get(method, "merge_commit")},
        )
        return self._pr(data)

    def get_status(self, ref):
        data = self.request(
            "GET", f"{self._repo}/commit/{quote(ref, safe='')}/statuses"
        )
        states = {s["state"] for s in data.get("values", ())}
        if not states:
            return ""
        if states & {"FAILED", "STOPPED"}:
            return "failure"
        if "INPROGRESS" in states:
            return "pending"
        return "success"
