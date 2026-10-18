# Contributing

## Set up

Use Linux and Python 3.10+. FFmpeg/ffprobe are needed for real media acquisition;
the offline tests use fixtures and do not contact the public relay services.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]' build
python -m pytest -q
```

## Edit, review and test

The source manifest records the files deliberately included in a release. After
editing code, tests or documentation, review your diff and update their hashes:

```bash
git diff
python scripts/check_release.py --refresh
python scripts/check_release.py
python -m pytest -q
python -m build
python scripts/check_sdist.py
```

Refreshing hashes is a record of the changed files; it does not review or certify
their contents. Include the manifest diff with your pull request. New release
files need an explicit path, for example:

```bash
python scripts/check_release.py --refresh --add src/social_fetch/new_adapter.py
```

If removing a file, deliberately remove its entry from `SOURCE-MANIFEST.json`,
then refresh. Do not include downloaded media, local job data, cookies, tokens,
environment files or worker logs in a change.

Version changes update `pyproject.toml`, `src/social_fetch/__init__.py` and the
manifest's version together. The documented high-level API is `Client`; modules
below it also serve a larger application, whose optional catalog/UI modules
are not part of this package.

## Platform changes

A new platform needs more than its name in a list. Include canonical public-URL
handling, bounded discovery, a download route and checks for identity, permitted
delivery hosts, transfer completeness and media output. Keep login requirements,
unsupported post types, formats and actual live evidence explicit. Upstream
yt-dlp extractor availability alone is not a completed integration or proof that
a route works from a datacenter.

Use small public test sources you are authorized to access. Run live checks with
a fresh data directory, retain canonical source URLs and measured receipts, and
keep media/private delivery URLs out of the repository. Offline tests must not
perform network calls. Describe the check performed in the pull request.

## Bug reports

Use the issue template with the release version, Linux/Python versions, command,
public source URL if shareable, and sanitized JSON output. For a failed source,
say whether search, acquisition, assembly or export failed. Do not attach worker
logs without reviewing them for temporary delivery URLs and tokens.
