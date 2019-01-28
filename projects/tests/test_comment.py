import copy

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from projects.models import ProjectComment


@pytest.mark.django_db(transaction=True)
class TestComment:
    client = APIClient()

    comment_test = {"content": "This is a test comment"}

    #################
    #     CREATE    #
    #################
    @pytest.mark.parametrize(
        "user, project, status_code",
        [
            (pytest.lazy_fixture("f_user"), pytest.lazy_fixture("f_project"), 201),
            (pytest.lazy_fixture("f_user"), None, 404),
        ],
    )
    def test_create(self, user, project, status_code):
        self.client.force_authenticate(user=user)

        project_id = getattr(project, "id", 999_999_999_999)
        url = reverse(
            "project-comments-list", kwargs={"parent_lookup_project": project_id}
        )

        response = self.client.post(url, data=self.comment_test)

        assert response.status_code == status_code

        if response.status_code == 201:
            comments = ProjectComment.objects.all()
            assert comments.count() == 1
            comment = comments.first()

            assert comment.user == user
            assert comment.content == self.comment_test["content"]

    #################
    #      LIST     #
    #################
    @pytest.mark.parametrize(
        "user, project, status_code, count",
        [
            (pytest.lazy_fixture("f_user"), pytest.lazy_fixture("f_project"), 200, 1),
            (pytest.lazy_fixture("f_user"), pytest.lazy_fixture("f_project"), 200, 0),
            (pytest.lazy_fixture("f_user"), None, 404, 0),
        ],
    )
    def test_list(self, user, project, status_code, count, comment_factory):
        self.client.force_authenticate(user=user)

        if count:
            for i in range(count):
                comment_factory(user=user, project=project)

        project_id = getattr(project, "id", 999_999_999_999)

        url = reverse(
            "project-comments-list", kwargs={"parent_lookup_project": str(project_id)}
        )
        response = self.client.get(url)

        assert response.status_code == status_code
        if response.status_code == 200:
            assert len(response.data["results"]) == count

    #################
    #    RETRIEVE   #
    #################
    @pytest.mark.parametrize(
        "user, comment, status_code",
        [
            (
                pytest.lazy_fixture("f_user"),
                pytest.lazy_fixture("f_comment_user1"),
                200,
            ),
            (
                pytest.lazy_fixture("f_user"),
                pytest.lazy_fixture("f_comment_user2"),
                200,
            ),
        ],
    )
    def test_retrieve(self, user, comment, status_code):
        self.client.force_authenticate(user=user)

        url = reverse(
            "project-comments-detail",
            kwargs={
                "parent_lookup_project": str(comment.project.id),
                "pk": str(comment.id),
            },
        )
        response = self.client.get(url)

        assert response.status_code == status_code

    #################
    #     UPDATE    #
    #################
    @pytest.mark.parametrize(
        "user, comment, status_code",
        [
            (
                pytest.lazy_fixture("f_user"),
                pytest.lazy_fixture("f_comment_user1"),
                200,
            ),
            (
                pytest.lazy_fixture("f_user"),
                pytest.lazy_fixture("f_comment_user2"),
                403,
            ),
        ],
    )
    def test_update(self, user, comment, status_code):
        self.client.force_authenticate(user=user)

        url = reverse(
            "project-comments-detail",
            kwargs={
                "parent_lookup_project": str(comment.project.id),
                "pk": str(comment.id),
            },
        )

        put_data = copy.deepcopy(self.comment_test)
        put_data["content"] = "testing_put"

        patch_data = {"content": "testing_patch"}

        response = self.client.put(url, put_data)
        assert response.status_code == status_code

        if response.status_code == 200:
            assert response.data["content"] == put_data["content"]

        response = self.client.patch(url, patch_data)
        assert response.status_code == status_code

        if response.status_code == 200:
            assert response.data["content"] == patch_data["content"]

    #################
    #     REMOVE    #
    #################
    @pytest.mark.parametrize(
        "user, comment, status_code",
        [
            (
                pytest.lazy_fixture("f_user"),
                pytest.lazy_fixture("f_comment_user1"),
                204,
            ),
            (
                pytest.lazy_fixture("f_user"),
                pytest.lazy_fixture("f_comment_user2"),
                403,
            ),
        ],
    )
    def test_remove(self, user, comment, status_code):
        self.client.force_authenticate(user=user)

        url = reverse(
            "project-comments-detail",
            kwargs={
                "parent_lookup_project": str(comment.project.id),
                "pk": str(comment.id),
            },
        )
        response = self.client.delete(url)

        assert response.status_code == status_code
