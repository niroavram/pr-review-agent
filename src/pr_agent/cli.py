"""`pr-agent` command line."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from dotenv import load_dotenv

from pr_agent.policy.config import CONFIG_FILE, TEMPLATE, parse_config

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Agentic PR review & autofix")


@app.callback()
def _main() -> None:
    load_dotenv()


@app.command()
def init(path: Path = typer.Argument(Path(".")), force: bool = False) -> None:
    """Copy the autonomy-boundaries template into a repo."""
    dest = path / CONFIG_FILE
    if dest.exists() and not force:
        typer.echo(f"{dest} exists (use --force to overwrite)")
        raise typer.Exit(1)
    shutil.copyfile(TEMPLATE, dest)
    typer.echo(f"wrote {dest}")


@app.command("check-config")
def check_config(path: Path = typer.Argument(Path("."))) -> None:
    """Validate a repo's .pr-agent.yml (or a file path)."""
    file = path if path.is_file() else path / CONFIG_FILE
    if not file.exists():
        typer.echo(f"✗ {file} not found -> agent runs fail-closed (suggest-only)")
        raise typer.Exit(1)
    try:
        parse_config(file.read_text())
    except ValueError as e:
        typer.echo(f"✗ {file}: {e}")
        raise typer.Exit(1) from e
    typer.echo(f"✓ {file} is valid")


@app.command()
def review(
    target: str = typer.Argument(None, help="GitHub PR URL"),
    local: Path = typer.Option(None, "--local", help="Local repo path (reviews HEAD vs --base)"),
    base: str = typer.Option("main", "--base"),
    head: str = typer.Option("HEAD", "--head"),
) -> None:
    """Review a PR (GitHub URL) or a local branch."""
    raise NotImplementedError("wired in Wave 1")


@app.command()
def demo() -> None:
    """Build the demo repo and review seeded case 01."""
    raise NotImplementedError("wired in Wave 1")


if __name__ == "__main__":
    app()
