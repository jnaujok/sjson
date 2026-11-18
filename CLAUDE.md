# Working on this repository

## Standing rules

- **Update README.md before merging.** Every change that adds or alters a
  feature, a behaviour, an API, a file format, benchmark figures or a known
  limitation updates README.md in the same pull request, before it is merged.
  If nothing in the README needs to change, say so in the pull request.
- **Update CHANGELOG.md before merging.** Every change gets an entry under
  `[Unreleased]` (Added / Changed / Fixed / Removed, as in Keep a Changelog)
  in the same pull request, before it is merged, noting any packet format
  version change. When a version is released, move the entries under its
  number and date.

## Checks

- `poetry run flake8 src tests examples` and `poetry run black --check src tests examples`
- `poetry run pytest`
