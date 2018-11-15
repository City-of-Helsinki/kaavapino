import os
from io import StringIO
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile, InMemoryUploadedFile
from rest_framework.exceptions import ValidationError

from projects.serializers.project import ProjectFileSerializer


@pytest.mark.django_db(transaction=True)
class TestProjectFileSerializer:
    @pytest.mark.parametrize(
        "section_attribute, attribute, project, raises_exception",
        [
            (
                pytest.lazy_fixture("f_project_section_attribute_6_file"),
                pytest.lazy_fixture("f_boolean_attribute"),
                pytest.lazy_fixture("f_project"),
                True,
            ),
            (
                None,
                pytest.lazy_fixture("f_file_attribute"),
                pytest.lazy_fixture("f_project"),
                True,
            ),
            (
                pytest.lazy_fixture("f_project_section_attribute_6_file"),
                pytest.lazy_fixture("f_file_attribute"),
                pytest.lazy_fixture("f_project"),
                False,
            ),
        ],
    )
    def test__validate_attribute(
        self, section_attribute, attribute, project, raises_exception
    ):

        if raises_exception:
            with pytest.raises(ValidationError):
                ProjectFileSerializer._validate_attribute(attribute, project)
        else:
            assert ProjectFileSerializer._validate_attribute(attribute, project) is None


    @pytest.mark.parametrize(
        "section_attribute, attribute, project, is_valid",
        [
            (
                pytest.lazy_fixture("f_project_section_attribute_6_file"),
                pytest.lazy_fixture("f_boolean_attribute"),
                pytest.lazy_fixture("f_project"),
                False,
            ),
            (
                None,
                pytest.lazy_fixture("f_file_attribute"),
                pytest.lazy_fixture("f_project"),
                False,
            ),
            (
                pytest.lazy_fixture("f_project_section_attribute_6_file"),
                pytest.lazy_fixture("f_file_attribute"),
                pytest.lazy_fixture("f_project"),
                True,
            ),
        ],
    )
    def test_serializer(
        self, section_attribute, attribute, project, is_valid
    ):
        attribute = attribute.identifier
        project = project.pk

        # Create a InMemoryUploadedFile just as the object that the request would
        # get when a file has been uploaded.
        io = StringIO("test")
        io.seek(0, os.SEEK_END)  # Change stream position to the end
        file_length = io.tell()  # Get size of file
        file = InMemoryUploadedFile(io, None, "foo.txt", "text", file_length, None)

        data = {"file": file, "attribute": attribute, "project": project}

        serializer = ProjectFileSerializer(data=data)
        assert serializer.is_valid() is is_valid
