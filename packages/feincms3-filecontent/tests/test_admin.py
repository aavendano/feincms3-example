import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from feincms3_filecontent import services
from feincms3_filecontent.content.documents import content_hash
from feincms3_filecontent.models import ContentIndex
from feincms3_filecontent.sync.engine import SyncEngine

from .conftest import git


pytestmark = pytest.mark.django_db

EDIT = reverse("admin:feincms3_filecontent_edit")


@pytest.fixture
def admin_client(client, content):
    user = User.objects.create_superuser(
        "ada", "ada@example.com", "pw", first_name="Ada", last_name="L"
    )
    client.force_login(user)
    SyncEngine.default().sync()
    return client


def test_changelist_shows_repository_state(admin_client):
    response = admin_client.get(
        reverse("admin:feincms3_filecontent_contentindex_changelist")
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "CLEAN" in body
    assert "blog/hello.md" in body


def test_change_view_redirects_to_editor(admin_client):
    obj = ContentIndex.objects.get(path="about.md")
    url = reverse("admin:feincms3_filecontent_contentindex_change", args=[obj.pk])
    response = admin_client.get(url)
    assert response.status_code == 302
    assert response["Location"] == f"{EDIT}?path=about.md"


def test_edit_commits_with_user_as_author(admin_client, content, remote):
    response = admin_client.get(EDIT, {"path": "about.md"})
    assert response.status_code == 200
    form = response.context["form"]
    assert form.initial["expected_hash"] == content_hash(
        (content / "about.md").read_bytes()
    )

    response = admin_client.post(
        EDIT,
        {
            "path": "about.md",
            "text": "---\ntitle: About\n---\nEdited in the admin.\n",
            "message": "Edit about in admin",
            "mode": "direct",
            "expected_hash": form.initial["expected_hash"],
        },
    )
    assert response.status_code == 302
    assert (
        git(remote, "log", "-1", "--format=%an <%ae>|%s")
        == "Ada L <ada@example.com>|Edit about in admin"
    )


def test_edit_shows_validation_and_stale_errors(admin_client):
    data = {
        "path": "about.md",
        "message": "x",
        "mode": "direct",
        "expected_hash": "stale",
    }
    response = admin_client.post(EDIT, {**data, "text": "---\ntitle: [x\n---\n"})
    assert "Invalid YAML" in response.content.decode()
    response = admin_client.post(EDIT, {**data, "text": "---\ntitle: ok\n---\n"})
    assert "changed by someone else" in response.content.decode()


def test_history_and_restore(admin_client, content):
    first = services.get_repository().current_sha()
    admin_client.post(
        EDIT,
        {
            "path": "about.md",
            "text": "---\ntitle: v2\n---\n",
            "message": "v2",
            "mode": "direct",
            "expected_hash": "",
        },
    )
    # expected_hash "" means "must not exist": the edit above is refused.
    assert "We sell" in (content / "about.md").read_text()

    history = reverse("admin:feincms3_filecontent_history")
    response = admin_client.get(history, {"path": "about.md"})
    assert response.status_code == 200
    assert "Initial content" in response.content.decode()

    response = admin_client.get(
        reverse("admin:feincms3_filecontent_diff"), {"path": "about.md", "sha": first}
    )
    assert "We sell" in response.content.decode()


def test_restore_view(admin_client, content):
    first = services.get_repository().current_sha()
    (content / "about.md").write_text("---\ntitle: v2\n---\n")
    git(content, "commit", "-qam", "v2")
    response = admin_client.post(
        reverse("admin:feincms3_filecontent_restore"),
        {
            "path": "about.md",
            "sha": first,
            "expected_hash": content_hash((content / "about.md").read_bytes()),
        },
    )
    assert response.status_code == 302
    assert "We sell" in (content / "about.md").read_text()


def test_sync_and_rebuild_buttons(admin_client):
    for name in ("sync", "rebuild"):
        response = admin_client.post(reverse(f"admin:feincms3_filecontent_{name}"))
        assert response.status_code == 302


def test_permissions_are_enforced(client, content):
    user = User.objects.create_user("bob", "bob@example.com", "pw", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_contentindex"))
    client.force_login(user)
    assert client.get(EDIT, {"path": "about.md"}).status_code == 403
    assert client.post(reverse("admin:feincms3_filecontent_rebuild")).status_code == 403
