import logging
import re
from typing import Iterable, Sequence

from openpyxl import load_workbook
from django.db import transaction

from projects.models import (
    ProjectType,
    Report,
    Attribute,
    CommonProjectPhase,
    Report,
    ReportColumn,
    ReportColumnPostfix,
)

logger = logging.getLogger(__name__)

# Sheets
REPORT_SHEET_NAME = "Sheet1"
EXPECTED_A1_VALUE = "rivi nro"

# Report sheet column titles
REPORT_NAME = "raportin nimi"
COLUMN_ATTRIBUTES = "kentät"
COLUMN_CONDITIONS = "näyttöehto"
COLUMN_POSTFIX = "loppuliite"
COLUMN_INDEX = "sarakkeiden järjestys"
COLUMN_TITLE = "sarakkeen otsikko"

# Hard-coded for now because only one report type is
# previewable at this point
# TODO check its name
PREVIEWABLE_REPORTS = []

class ReportImporterException(Exception):
    pass


class ReportImporter:
    """Import reports from an Excel file"""
    def __init__(self, options=None):
        self.options = options
        self.workbook = None

    def _open_workbook(self, filename):
        try:
            return load_workbook(filename, read_only=True, data_only=True)
        except FileNotFoundError as e:
            raise ReportImporterException(e)

    def _extract_data_from_workbook(self, workbook):
        try:
            report_sheet = workbook[REPORT_SHEET_NAME]
        except KeyError as e:
            raise ReportImporterException(e)

        report_sheet_a1_value = report_sheet["A1"].value
        invalid_sheet_exception = ReportImporterException(
            "This does not seem to be a valid report type sheet."
        )
        try:
            if report_sheet_a1_value.lower() != EXPECTED_A1_VALUE:
                raise invalid_sheet_exception
        except AttributeError:
            raise invalid_sheet_exception

        return self._rows_for_report_sheet(report_sheet)

    def _rows_for_report_sheet(self, sheet):
        data = []

        for row in list(sheet.iter_rows()):
            if not row[1].value:
                break
            data.append([col.value for col in row])

        return data

    def _set_row_indexes(self, header_row: Iterable[str]):
        """Determine index number for all columns."""
        self.column_index: dict = {}

        for index, column in enumerate(header_row):
            if column:
                self.column_index[column.lower()] = index

    def _check_if_row_valid(self, row: Sequence) -> bool:
        """Check if the row has all required data."""
        try:
            assert(row[self.column_index[REPORT_NAME]])
        except AssertionError:
            logger.info(f"Invalid row missing report name not imported.")
            return False

        return True

    def _create_report_columns(self, rows):
        project_type, _ = ProjectType.objects.get_or_create(name="asemakaava")
        ReportColumn.objects.all().delete()
        ReportColumnPostfix.objects.all().delete()

        for row in rows:
            report_name = row[self.column_index[REPORT_NAME]]
            report, _ = Report.objects.get_or_create(
                name=report_name,
                project_type=project_type,
                defaults={
                    "is_admin_report": True,
                    "show_created_at": True,
                    "show_modified_at": True,
                    "previewable": report_name in PREVIEWABLE_REPORTS,
                }
            )

            column = ReportColumn.objects.create(
                report=report,
                title=row[self.column_index[COLUMN_TITLE]],
                index=row[self.column_index[COLUMN_INDEX]] or 0,
            )

            attributes = \
                (row[self.column_index[COLUMN_ATTRIBUTES]] or "").split(",")
            conditions = \
                (row[self.column_index[COLUMN_CONDITIONS]] or "").split(",")

            column.attributes.set(
                Attribute.objects.filter(identifier__in=attributes)
            )
            column.condition.set(
                Attribute.objects.filter(identifier__in=conditions)
            )

            try:
                postfixes = zip(
                    re.findall(
                        r"\[([X,S,M,L]*)\]",
                        row[self.column_index[COLUMN_POSTFIX]],
                    ),
                    re.findall(
                        r'"([^"]*)"',
                        row[self.column_index[COLUMN_POSTFIX]],
                    ),
                )
            except TypeError:
                postfixes = []

            for phases, formatting in postfixes:
                postfix = ReportColumnPostfix.objects.create(
                    report_column=column,
                    formatting=formatting,
                )
                postfix.phases.set(
                    CommonProjectPhase.objects.filter(
                        name__in=phases.split(","),
                    )
                )

    @transaction.atomic
    def run(self):
        filename = self.options.get("filename")
        logger.info(f"Importing report types and columns from {filename}")

        self.workbook = self._open_workbook(filename)

        data_rows = \
            self._extract_data_from_workbook(self.workbook)
        header_row = data_rows.pop(0)
        # the second row is reserved for column descriptions, remove it as well
        data_rows.pop(0)
        self._set_row_indexes(header_row)
        data_rows = [
            row for row in data_rows
            if self._check_if_row_valid(row)
        ]
        self._create_report_columns(data_rows)
