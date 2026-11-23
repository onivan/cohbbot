# Internal development-time report

`dev_time_report.py` is a standalone documentation tool. It is not imported by the application, bot, deployment hooks, or test suite.

Run it from any directory inside the Git repository:

```sh
python3 docs/internal/dev_time_report.py
```

By default it writes `docs/internal/development_time_report.csv`. Use `--output -` to print CSV to stdout or `--output path/to/report.csv` to choose another destination.

The CSV columns are `hours`, `date`, and `tasks`. Multiple task descriptions for a day are joined with `; ` inside the CSV field.

## Estimation rules and limits

Git does not record time spent working, and file modification times are not reliable historical data after checkout, clone, or archive extraction. The report is therefore an estimate based on author timestamps and commit subjects, not a timesheet:

- reads unique, non-merge commits reachable from local and remote refs;
- ignores commits scoped as `(coord)` by default and excludes commits that only touch `docs/internal/`; commits titled `docs(internal): ...` are also excluded, including ones that update `BOARD.md`;
- groups same-day commits into sessions; a gap greater than 3 hours starts a new session;
- estimates each session as the time between its first and last commit plus 0.5 hours, with a 1-hour minimum and no upper limit;
- adds session estimates per day and rounds the daily total to the nearest integer hour, with half hours rounded up;
- removes conventional commit prefixes, keeps the first clause, and limits task labels to 12 words; known Ukrainian commit subjects are translated. Unknown non-English subjects fall back to `Update the application`.

These assumptions can over- or under-estimate actual effort. Adjust the session assumptions with `--idle-gap-hours`, `--padding-hours`, and `--minimum-session-hours`. Use `--include-coordination` to count `(coord)` commits. Internal paths and commits titled `docs(internal): ...` are excluded, so refreshing the report does not count the report-generation commit as application work.
