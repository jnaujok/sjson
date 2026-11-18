# Working on this repository

## Standing rules

- **Update README.md before merging.** Every change that adds or alters a
  feature, a behaviour, an API, a file format, benchmark figures or a known
  limitation updates README.md in the same pull request, before it is merged.
  If nothing in the README needs to change, say so in the pull request.

## Checks

- `poetry run flake8 src tests examples` and `poetry run black --check src tests examples`
- `poetry run pytest`
