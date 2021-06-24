from projects.models import ProjectType, Report, Attribute, ReportColumn


class ReportTypeCreator:
    def run(self):
        project_type, _ = ProjectType.objects.get_or_create(name="asemakaava")
        all_attributes, _ = Report.objects.update_or_create(
            name="Kaikki kentät",
            project_type=project_type,
            defaults={
                "is_admin_report": True,
                "show_name": True,
                "show_created_at": True,
                "show_modified_at": True,
                "show_user": True,
                "show_phase": True,
                "show_subtype": True,
            },
        )
        all_attributes.report_attributes.all().delete()

        for attribute in Attribute.objects.report_friendly():
            column = ReportColumn.objects.create(report=all_attributes)
            columns.attributes.set([attribute])
