.PHONY: lint format test check build clean release help

.DEFAULT_GOAL = help

require-%:
	@ if [ "${${*}}" = "" ]; then \
		echo "ERROR: Environment variable not set: \"$*\""; \
		exit 1; \
	fi

## Run ruff lint and format check
lint:
	@ruff check .
	@ruff format --check .

## Reformat and auto-fix with ruff
format:
	@ruff check --fix .
	@ruff format .

## Run the test suite (optionally pass ARGS, e.g. ARGS="-k upload")
test:
	@pytest ${ARGS}

## Run everything the pr-checks workflow runs
check: lint test

## Build sdist and wheel into dist/ and validate them
build: clean-build
	@python -m build
	@python -m twine check dist/*

## Remove build artifacts
clean-build:
	@rm -rf build dist *.egg-info

## Nukes build artifacts and devenv and starts over
clean: clean-build
	@rm -rf .devenv
	@rm -rf .direnv
	@find . -type d -name __pycache__ -prune -exec rm -rf {} +
	@rm -rf .pytest_cache .ruff_cache

## Bump the version, commit and tag it (pass VERSION=x.y.z). Push the tag to publish.
release: require-VERSION
	@if ! git diff --quiet || ! git diff --cached --quiet; then \
		echo "ERROR: working tree is not clean, commit or stash first"; \
		exit 1; \
	fi
	@if git rev-parse -q --verify "refs/tags/v${VERSION}" > /dev/null; then \
		echo "ERROR: tag v${VERSION} already exists"; \
		exit 1; \
	fi
	@$(MAKE) check
	@uv version ${VERSION}
	@git add pyproject.toml uv.lock
	@# Nothing to commit when the version was already set, e.g. the first release
	@git diff --cached --quiet || git commit -m "release v${VERSION}"
	@git tag -m "v${VERSION}" "v${VERSION}"
	@echo
	@echo "Tagged v${VERSION}. To publish to PyPI run:"
	@echo "  git push origin main v${VERSION}"

## Show help screen.
help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo
	@awk '/^[a-zA-Z\-0-9_]+:/ { \
		helpMessage = match(lastLine, /^## (.*)/); \
		if (helpMessage) { \
			helpCommand = substr($$1, 0, index($$1, ":")-1); \
			helpMessage = substr(lastLine, RSTART + 3, RLENGTH); \
			printf "%-30s %s\n", helpCommand, helpMessage; \
		} \
	} \
	{ lastLine = $$0 }' $(MAKEFILE_LIST)
