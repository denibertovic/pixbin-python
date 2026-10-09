{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # https://devenv.sh/basics/

  # https://devenv.sh/languages/
  languages.python.enable = true;
  languages.python.version = "3.13";
  languages.python.uv.enable = true;
  # `uv sync` installs the runtime deps plus the dev dependency group, which
  # pulls in the dev and full extras. Running `uv sync` by hand does the same.
  languages.python.uv.sync.enable = true;
  languages.python.venv.enable = true;
  languages.python.venv.quiet = true;

  enterShell = ''
    echo "##############################################"
    echo "Welcome to the pixbin-python development shell"
    echo "  ruff check .          lint"
    echo "  ruff format .         format"
    echo "  pytest                run tests"
    echo "  python -m build       build sdist and wheel"
    echo "##############################################"
  '';

  # https://devenv.sh/tests/
  # Same gates as the pr-checks workflow.
  enterTest = ''
    ruff check .
    ruff format --check .
    pytest
  '';

  # we use .envrc to source that
  dotenv.disableHint = true;

  git-hooks.hooks = {
    ruff = {
      enable = true;
      entry = "ruff check --fix";
    };
    ruff-format = {
      enable = true;
      entry = "ruff format";
    };
  };

  # See full reference at https://devenv.sh/reference/options/
}
