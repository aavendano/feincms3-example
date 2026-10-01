from urllib.parse import quote

from .base import GitProvider, PullRequest


class GitLabProvider(GitProvider):
    """
    ``OPTIONS = {"project": "group/name", "token_env": "GITLAB_TOKEN"}``

    Set ``api_url`` for self-hosted GitLab (``https://host/api/v4``).
    """

    api_url = "https://gitlab.com/api/v4"

    def __init__(self, *, project, **kwargs):
        super().__init__(**kwargs)
        self.project = project

    def headers(self):
        return {"Accept": "application/json", "PRIVATE-TOKEN": self._token}

    @property
    def _project(self):
        return f"/projects/{quote(self.project, safe='')}"

    def _mr(self, data):
        state = {"opened": "open", "merged": "merged"}.get(data["state"], "closed")
        return PullRequest(
            number=data["iid"],
            url=data["web_url"],
            state=state,
            title=data["title"],
            head=data["source_branch"],
            base=data["target_branch"],
            review_state="approved" if data.get("approved") else "",
            raw=data,
        )

    def create_pull_request(self, *, head, base, title, body=""):
        data = self.request(
            "POST",
            f"{self._project}/merge_requests",
            {
                "source_branch": head,
                "target_branch": base,
                "title": title,
                "description": body,
            },
        )
        return self._mr(data)

    def get_pull_request(self, number):
        return self._mr(
            self.request("GET", f"{self._project}/merge_requests/{int(number)}")
        )

    def find_pull_request(self, *, head, base):
        data = self.request(
            "GET",
            f"{self._project}/merge_requests?state=opened"
            f"&source_branch={quote(head, safe='')}&target_branch={quote(base, safe='')}",
        )
        return self._mr(data[0]) if data else None

    def merge_pull_request(self, number, *, method="merge"):
        payload = {"squash": method == "squash"}
        data = self.request(
            "PUT", f"{self._project}/merge_requests/{int(number)}/merge", payload
        )
        return self._mr(data)

    def get_status(self, ref):
        data = self.request(
            "GET", f"{self._project}/repository/commits/{quote(ref, safe='')}"
        )
        status = (data.get("last_pipeline") or {}).get("status", "")
        return {"success": "success", "failed": "failure", "canceled": "failure"}.get(
            status, "pending" if status else ""
        )
