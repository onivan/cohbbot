import csv
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_time_report


class DevTimeReportTests(unittest.TestCase):
    def test_conventional_subject_becomes_short_sentence(self):
        self.assertEqual(
            dev_time_report.describe_task("feat(api): add monthly report endpoint"),
            "Add monthly report endpoint.",
        )

    def test_known_ukrainian_subject_is_translated(self):
        self.assertEqual(
            dev_time_report.describe_task("Додати журнал сповіщень адміністратора"),
            "Add the admin notifications inbox.",
        )

    def test_unknown_cyrillic_subject_uses_english_fallback(self):
        self.assertEqual(
            dev_time_report.describe_task("Невідома нова задача"),
            "Update the application.",
        )

    def test_long_subject_is_shortened_to_first_clause(self):
        task = dev_time_report.describe_task(
            "fix(db): ensure all IDs and keys are stripped and cast to strings "
            "for reliable matching; add additional logging"
        )
        self.assertEqual(
            task,
            "Ensure all IDs and keys are stripped and cast to strings for...",
        )
        self.assertNotIn(";", task)

    def test_sessions_split_after_idle_gap_and_round_daily_total(self):
        events = [
            dev_time_report.CommitEvent(datetime(2026, 1, 5, 10, tzinfo=timezone.utc), "feat: add A"),
            dev_time_report.CommitEvent(datetime(2026, 1, 5, 11, tzinfo=timezone.utc), "fix: update B"),
            dev_time_report.CommitEvent(datetime(2026, 1, 5, 15, tzinfo=timezone.utc), "docs: explain C"),
        ]
        rows = dev_time_report.build_daily_rows(events)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-01-05")
        self.assertEqual(rows[0]["hours"], 3)
        self.assertEqual(
            rows[0]["tasks"],
            "Add A.; Update B.; Explain C.",
        )

    def test_csv_has_requested_columns_and_semicolon_joined_tasks(self):
        output = io.StringIO()
        dev_time_report.write_csv(
            [{"hours": 2, "date": "2026-01-05", "tasks": "Add A.; Fix B."}],
            output,
        )
        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual(list(rows[0]), ["hours", "date", "tasks"])
        self.assertEqual(rows[0]["hours"], "2")
        self.assertEqual(rows[0]["tasks"], "Add A.; Fix B.")


if __name__ == "__main__":
    unittest.main()
