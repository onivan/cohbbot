#!/usr/bin/env python3
"""Create an internal, Git-based estimate of development time by day.

This is an estimate from commit timestamps, not a timesheet or measured work log.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

DEFAULT_IDLE_GAP_HOURS = 3.0
DEFAULT_PADDING_HOURS = 0.5
DEFAULT_MIN_SESSION_HOURS = 1.0
MAX_TASK_WORDS = 12

COMMIT_PREFIX = re.compile(
    r"^(?:feat|fix|docs|test|chore|refactor|build|ci|perf|style)"
    r"(?:\([^)]+\))?!?:\s*",
    re.IGNORECASE,
)
COORDINATION_COMMIT = re.compile(r"^\w+\(coord\):", re.IGNORECASE)
INTERNAL_REPORT_COMMIT = re.compile(r"^docs\(internal\):", re.IGNORECASE)
CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")

# Short, plain-English descriptions for the existing Ukrainian commit subjects.
# Add entries here when new non-English subjects need a more exact report label.
TRANSLATIONS = {
    "docs(plan): уточнити ux погодження чеків": "Clarify the receipt review flow",
    "docs(coord): регламент роботи 2 робочих місць / 2 агентів (послідовно)": "Document the two-workstation development workflow",
    "fix(deps): оголосити itsdangerous (прямо імпортується у webapp.py)": "Declare itsdangerous as an application dependency",
    "chore(deploy): git-деплой на vps (bare-репо + post-receive) + makefile": "Set up Git-based deployment to the VPS",
    "test(vps): test_centers_own.py — перевірка «свого цн» (f6) і прав доступу (h1) на staging": "Test center ownership and access rights on staging",
    "fix(admin): надійне визначення «свого» цн + cache-busting статики": "Fix own-center detection and static asset caching",
    "docs(todo): h1 — відсутня перевірка прав на get /api/budgets/center/{center_id}": "Document the missing budget access check",
    "fix(webapp): головний екран адміна цн — зведення по всіх центрах": "Show all centers on the admin dashboard",
    "feat(ai): розпізнавання чеків через openrouter + керування ai-моделями в адмінці": "Add receipt recognition with OpenRouter and admin model controls",
    "feat(ai): a1 — валідація «це чек?» (is_receipt/document_type) + відхилення не-чеків із сповіщенням адміну": "Validate receipt documents and notify admins about non-receipts",
    "feat(web): f4 — кнопки дій у модалках перенесено наверх (sticky), модалки прокручуються": "Move modal actions to the top and allow modal scrolling",
    "feat(web): f1-f3 ux — закриття модалок по esc/backdrop, свайп між витратами, вибір камера/галерея": "Improve modal dismissal, expense navigation, and photo selection",
    "додати журнал сповіщень адміністратора": "Add the admin notifications inbox",
    "fix(cash): return журналу був усередині циклу (дані завжди null)": "Fix the cash ledger response",
    "fix: вирівняти відступи після правок (webapp/database)": "Fix formatting in the web app and database code",
    "fix(cash): виправити відступ у csv-експорті (indentationerror), прибрати smoke-скрипт": "Fix CSV export and remove the smoke test script",
    "fix(cash): журнал віддає status/matches, csv показує стан місяця": "Fix cash ledger results and monthly status in CSV",
    "chore: прибрати тимчасовий smoke-скрипт з репозиторію": "Remove the temporary smoke test script",
    "fix(cash): ascii-ім'я файлу в content-disposition (500 на кирилиці в назві цн)": "Fix export filenames for centers with non-English names",
    "feat(cash): j4 — річний огляд цн, закриття/відкриття місяця, звірка, csv-експорт": "Add yearly cash reports, reconciliation, and CSV export",
    "docs(todo): h2 — secret_key не заданий у .env, сесії злітають на кожному рестарті": "Document the missing persistent session key",
    "feat(cash): вкладка «кошти» (read-only) + «бюджет» -> «ліміти» (j2)": "Add the read-only cash tab and rename budgets to limits",
    "docs(todo): етап 3 обліку коштів виконано; фактичні api, хук витрат і сповіщення": "Document cash accounting milestone 3",
    "feat(cash): етап 3 — адмінські операції з коштами цн (api, вкладка «кошти», сповіщення в бот)": "Add admin cash operations and bot notifications",
    "chore: tmp/ у gitignore; етап 1 обліку коштів позначено виконаним (smoke 32/32 на staging)": "Ignore temporary files and document cash accounting milestone 1",
    "fix(cash): ланцюжок перерахунку — до останнього місяця з даними, закриті місяці перевідкриваються з аудитом": "Fix cash balance recalculation and audit reopening",
    "feat(cash): облік коштів цн — схема (settings/operations/month_balances/audit) і розрахунок залишків": "Add the cash accounting schema and balance calculations",
    "docs(todo): розділ j — облік реальних коштів цн (каса), етапи та правила звірки": "Document the cash accounting plan",
    "docs: прод на mysql (cohbbot_prod), залежності venv ставляться вручну, обмеження journalctl": "Document production MySQL and deployment requirements",
    "fix(deploy): copy-db переносить users/expenses (telegram_id — id користувача, не бота); docs: .env.example + де живуть .env": "Fix database copy and document environment files",
    "fix(deploy): copy-db — не падати мовчки, якщо в .env немає ключа": "Report missing database configuration during copy",
    "feat(deploy): скрипт перенесення даних staging-бд -> прод-бд (окремі боти => окремі telegram_id)": "Add the staging-to-production database copy script",
    "docs(todo): локальний клон гілки main + правило проти гарячих правок на vps": "Document the local production clone and VPS change policy",
    "chore(secrets): адреса vps — у .vps.env (gitignore) замість todo/makefile/deploy.sh": "Move the VPS address into the ignored environment file",
    "chore(deploy): локальний клон як робоче середовище — deploy.sh через ssh, make test на vps, регламент у todo": "Set up local development and Git-based deployment",
    "fix(deploy): хук — unset git_dir/git_work_tree (git виставляє їх для хуків)": "Fix Git environment variables in the deployment hook",
    "fix(deploy): fetch перед порівнянням, інакше 'нічого нового' — хибне": "Fetch before comparing deployment refs",
    "docs(todo): регламент розробки/деплою (remote-ssh, git-деплой, staging/prod)": "Document development and deployment workflow",
    "docs: план покращень (todo) + project_overview; узгоджено схеми d1/d2, b3, g1": "Document the project plan and architecture",
}


@dataclass(frozen=True)
class CommitEvent:
    timestamp: datetime
    subject: str


def git_root(start: Path | None = None) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def read_commit_events(repo_root: Path, include_coordination: bool = False) -> list[CommitEvent]:
    """Read unique, non-merge commits that touch files outside this internal tool."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--all",
            "--no-merges",
            "--format=%aI%x1f%H%x1f%s",
            "--",
            ".",
            ":(exclude)docs/internal/**",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    events = []
    seen = set()
    for line in result.stdout.splitlines():
        fields = line.split("\x1f", 2)
        if len(fields) != 3:
            continue
        timestamp_text, commit_hash, subject = fields
        if commit_hash in seen:
            continue
        seen.add(commit_hash)
        if INTERNAL_REPORT_COMMIT.match(subject.strip()):
            continue
        if not include_coordination and COORDINATION_COMMIT.match(subject.strip()):
            continue
        timestamp = datetime.fromisoformat(timestamp_text)
        events.append(CommitEvent(timestamp=timestamp, subject=subject.strip()))
    return events


def describe_task(subject: str) -> str:
    """Normalize a commit subject into a short English task sentence."""
    subject = re.sub(r"\s+", " ", subject.strip())
    translated = TRANSLATIONS.get(subject.casefold())
    if translated:
        return translated.rstrip(".!?;") + "."

    task = COMMIT_PREFIX.sub("", subject).strip()
    task = task.split("; ", 1)[0].strip(" .;:")
    task = task.replace(" -> ", " to ").replace("&", "and")
    task = re.sub(r"\s+", " ", task)
    if not task or CYRILLIC.search(task):
        task = "Update the application"
    words = task.split()
    if len(words) > MAX_TASK_WORDS:
        task = " ".join(words[:MAX_TASK_WORDS]) + "..."
    task = task[0].upper() + task[1:]
    if task[-1] not in ".!?":
        task += "."
    return task


def split_sessions(events: list[CommitEvent], idle_gap_hours: float) -> list[list[CommitEvent]]:
    if not events:
        return []
    ordered = sorted(events, key=lambda event: event.timestamp)
    gap_limit = idle_gap_hours * 3600
    sessions = [[ordered[0]]]
    for event in ordered[1:]:
        idle_seconds = (event.timestamp - sessions[-1][-1].timestamp).total_seconds()
        if idle_seconds > gap_limit:
            sessions.append([event])
        else:
            sessions[-1].append(event)
    return sessions


def estimate_session_hours(
    session: list[CommitEvent],
    padding_hours: float,
    minimum_hours: float,
) -> float:
    span_hours = (session[-1].timestamp - session[0].timestamp).total_seconds() / 3600
    return max(minimum_hours, span_hours + padding_hours)


def round_hours(hours: float) -> int:
    """Round positive estimates to the nearest whole hour (half up)."""
    return math.floor(hours + 0.5)


def build_daily_rows(
    events: list[CommitEvent],
    idle_gap_hours: float = DEFAULT_IDLE_GAP_HOURS,
    padding_hours: float = DEFAULT_PADDING_HOURS,
    minimum_hours: float = DEFAULT_MIN_SESSION_HOURS,
) -> list[dict[str, object]]:
    events_by_day: dict[str, list[CommitEvent]] = defaultdict(list)
    for event in events:
        # Keep the calendar date written in the commit's author timezone.
        events_by_day[event.timestamp.date().isoformat()].append(event)

    rows = []
    for date in sorted(events_by_day):
        day_events = events_by_day[date]
        sessions = split_sessions(day_events, idle_gap_hours)
        total_hours = sum(
            estimate_session_hours(session, padding_hours, minimum_hours)
            for session in sessions
        )
        tasks = []
        for event in sorted(day_events, key=lambda item: item.timestamp):
            task = describe_task(event.subject)
            if task not in tasks:
                tasks.append(task)
        rows.append({"hours": round_hours(total_hours), "date": date, "tasks": "; ".join(tasks)})
    return rows


def write_csv(rows: list[dict[str, object]], output: TextIO) -> None:
    writer = csv.DictWriter(output, fieldnames=("hours", "date", "tasks"), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write an internal, estimated Git development-time report as CSV."
    )
    parser.add_argument(
        "--output",
        default="docs/internal/development_time_report.csv",
        help="CSV destination relative to the repository root; use '-' for stdout.",
    )
    parser.add_argument(
        "--idle-gap-hours",
        type=float,
        default=DEFAULT_IDLE_GAP_HOURS,
        help=f"Split sessions after this idle gap (default: {DEFAULT_IDLE_GAP_HOURS:g}).",
    )
    parser.add_argument(
        "--padding-hours",
        type=float,
        default=DEFAULT_PADDING_HOURS,
        help=f"Add this estimate to each session span (default: {DEFAULT_PADDING_HOURS:g}).",
    )
    parser.add_argument(
        "--minimum-session-hours",
        type=float,
        default=DEFAULT_MIN_SESSION_HOURS,
        help=f"Minimum estimate per active session (default: {DEFAULT_MIN_SESSION_HOURS:g}).",
    )

    parser.add_argument(
        "--include-coordination",
        action="store_true",
        help="Include commits whose subject uses a '(coord)' scope.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (
        not math.isfinite(args.idle_gap_hours)
        or args.idle_gap_hours <= 0
        or not math.isfinite(args.padding_hours)
        or args.padding_hours < 0
        or not math.isfinite(args.minimum_session_hours)
        or args.minimum_session_hours <= 0
    ):
        print("Invalid estimate settings; check the hours options.", file=sys.stderr)
        return 2

    repo_root = git_root(Path.cwd())
    events = read_commit_events(repo_root, include_coordination=args.include_coordination)
    rows = build_daily_rows(
        events,
        idle_gap_hours=args.idle_gap_hours,
        padding_hours=args.padding_hours,
        minimum_hours=args.minimum_session_hours,
    )

    if args.output == "-":
        write_csv(rows, sys.stdout)
        return 0

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo_root / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output:
        write_csv(rows, output)
    print(f"Wrote {len(rows)} daily rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
