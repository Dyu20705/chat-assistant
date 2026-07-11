# ollama-discord

Small Python Discord bot that connects Discord commands to a local Ollama runtime.

## Local CI Checks

Use the same commands as GitHub Actions:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m compileall -q bot.py tests
python -c "import bot; print('import ok')"
ruff check .
pytest --cov --cov-report=term-missing
pip-audit --cache-dir .pip-audit-cache --skip-editable
actionlint .github/workflows/ci.yml
git diff --check
```

Set `OLLAMA_DISCORD_SKIP_DOTENV=1` when running checks against a local checkout
that has a production `.env` file. The checks do not need Discord, Ollama, or
repository secrets.
