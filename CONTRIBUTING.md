# Contributing

Thanks for helping improve Career Radar. Documentation corrections, reproducible bug reports, tests, and focused code changes are welcome.

## Report a problem

[Open an issue](https://github.com/Zack0303/career-radar/issues/new/choose) with the expected and actual behavior, Python and OS versions, the command (without private values), and a short sanitized error. For ATS issues include the provider and only a public, officially published board URL if needed. Never include real resumes, personal contact details, credentials, private workspace files, database contents, or confidential employer material. Replace any sample data with fictional data.

## Make a change

1. Fork and clone the repository; create a descriptive branch.
2. Keep changes focused. For significant changes, describe the problem in an issue first so the approach can be discussed.
3. Use Python 3.9-compatible code and preserve the standard-library-only core. Use entirely fictional data for fixtures, examples, and tests.
4. From the repository root, run:

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   PYTHONPATH=src python3 -m career_radar demo --out /tmp/career-radar-demo
   ```

5. Open a pull request explaining the problem, the change, how it was tested, and any known limitations. Update relevant documentation when behavior changes.

The tool's evidence validator has intentionally limited checks; do not describe it as a guarantee that claims are true. See [AGENTS.md](AGENTS.md) for repository-specific development rules and [the architecture](docs/ARCHITECTURE.md) for details.
