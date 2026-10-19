"""Command line: ``d2bg serve`` starts everything; the rest are tools and shortcuts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from d2bg import __version__, paths

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Dota 2 companion (GSI + public data).")
data_app = typer.Typer(no_args_is_help=True, help="Refresh and inspect the data snapshot.")
gsi_app = typer.Typer(no_args_is_help=True, help="Install, remove and check the GSI config.")
app.add_typer(data_app, name="data")
app.add_typer(gsi_app, name="gsi")


def _echo_json(doc: object) -> None:
    typer.echo(json.dumps(doc, indent=2, ensure_ascii=False))


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


# ── data ───────────────────────────────────────────────────────────


@data_app.command("refresh")
def data_refresh(
    steps: Annotated[str, typer.Option(help="Comma-separated steps, or 'all'.")] = "all",
    to_snapshot: Annotated[bool, typer.Option(help="Write into the committed data/snapshot.")] = False,
    max_calls: Annotated[int, typer.Option(help="Max /publicMatches pages for the matchups step.")] = 600,
    import_pages: Annotated[
        Path | None, typer.Option(help="Build matchups from saved /publicMatches pages instead.")
    ] = None,
) -> None:
    """Fetch fresh data from OpenDota (about 650 requests for everything; the free limit is ~3,000 a day)."""
    from d2bg.opendota import OpenDotaClient
    from d2bg.pipeline.refresh import STEPS, Refresher
    from d2bg.settings import SettingsStore

    out = paths.snapshot_dir() if to_snapshot else paths.refreshed_data_dir()
    client = OpenDotaClient(api_key=SettingsStore().get().opendota_api_key)

    def progress(step: str, done: int, total: int, message: str) -> None:
        if total > 1 and done % 10 == 0:
            typer.echo(f"  {step}: {done}/{total} {message}", err=True)

    refresher = Refresher(client, out, progress)
    chosen = list(STEPS) if steps == "all" else [s.strip() for s in steps.split(",") if s.strip()]
    if import_pages is not None:
        result = refresher.import_public_pages(import_pages)
        typer.echo(f"matchups: {result.rows} matches from {import_pages}")
        chosen = [s for s in chosen if s != "matchups"]
    for result in refresher.run(chosen, **({"max_calls": max_calls} if "matchups" in chosen else {})):
        typer.echo(
            f"{result.step}: {result.rows} rows, {result.calls} API calls, {result.seconds}s "
            f"{result.note}".rstrip()
        )
    typer.echo(f"wrote {out}; OpenDota usage: {client.usage()}")


@data_app.command("status")
def data_status() -> None:
    """Show which data files are in use and where they came from."""
    from d2bg.datastore import DataStore

    _echo_json(DataStore().status())


@app.command()
def train(
    to_snapshot: Annotated[bool, typer.Option(help="Write into the committed data/snapshot.")] = False,
) -> None:
    """Retrain the draft win-probability model from the stored public matches (needs the [train] extra)."""
    from d2bg.opendota import OpenDotaClient
    from d2bg.pipeline.refresh import Refresher, read_json

    out = paths.snapshot_dir() if to_snapshot else paths.refreshed_data_dir()
    if not (out / "public_matches.jsonl.gz").exists():
        out_src = paths.snapshot_dir()
        typer.echo(f"no public_matches.jsonl.gz in {out}; using {out_src}", err=True)
        out = out_src
    result = Refresher(OpenDotaClient(), out).run(["draft_model"])[0]
    report = read_json(out / "draft_model.json")["report"]
    typer.echo(f"{result.note}; report: {json.dumps(report, indent=2)}")


# ── gsi ────────────────────────────────────────────────────────────


@gsi_app.command("status")
def gsi_status(
    path: Annotated[Path | None, typer.Option(help="The 'dota 2 beta' folder.")] = None, port: int = 4242
) -> None:
    """Where Dota is and whether this app's GSI config is installed."""
    from d2bg.gsi import installer
    from d2bg.settings import SettingsStore

    _echo_json(installer.status(path or installer.find_dota(), port, SettingsStore().get().gsi_token))


@gsi_app.command("install")
def gsi_install(
    path: Annotated[Path | None, typer.Option(help="The 'dota 2 beta' folder.")] = None, port: int = 4242
) -> None:
    """Write gamestate_integration_d2bg.cfg into Dota's cfg folder (the only file this app writes there)."""
    from d2bg.gsi import installer
    from d2bg.settings import SettingsStore

    dota = path or installer.find_dota()
    if dota is None:
        typer.echo('Dota 2 not found; pass --path "...\\steamapps\\common\\dota 2 beta"', err=True)
        raise typer.Exit(1)
    target = installer.install(dota, port, SettingsStore().get().gsi_token)
    typer.echo(
        f"installed {target}\nRestart Dota 2 if it is running. If no data arrives, add "
        "-gamestateintegration to Dota's launch options in Steam yourself."
    )


@gsi_app.command("remove")
def gsi_remove(path: Annotated[Path | None, typer.Option(help="The 'dota 2 beta' folder.")] = None) -> None:
    """Delete this app's GSI config (and nothing else)."""
    from d2bg.gsi import installer

    dota = path or installer.find_dota()
    if dota is None:
        typer.echo("Dota 2 not found", err=True)
        raise typer.Exit(1)
    typer.echo("removed" if installer.remove(dota) else "nothing to remove")


# ── run ────────────────────────────────────────────────────────────


@app.command()
def serve(
    port: int = 4242,
    lan: Annotated[
        bool, typer.Option(help="Also listen on the local network (phone); needs the LAN token.")
    ] = False,
    demo: Annotated[str | None, typer.Option(help="Start a synthetic demo match for this hero.")] = None,
    replay: Annotated[Path | None, typer.Option(help="Replay a recorded .jsonl.gz session.")] = None,
    speed: float = 8.0,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open the browser.")] = True,
) -> None:
    """Start the app: GSI receiver, API and UI on http://127.0.0.1:<port>."""
    import threading
    import webbrowser

    import uvicorn

    from d2bg.api.app import create_app
    from d2bg.gsi import recorder
    from d2bg.gsi.demo import demo_frames

    application = create_app(port=port, lan=lan)
    svc = application.state.services
    if demo:
        svc.start_player(demo_frames(svc.ctx, demo), "demo", speed)
    elif replay:
        svc.start_player(list(recorder.read(replay)), "replay", speed)
    host = "0.0.0.0" if lan else "127.0.0.1"  # noqa: S104 - LAN mode is opt-in and token-guarded
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"d2bg {__version__} on {url}  (Ctrl+C to stop)")
    if lan:
        typer.echo(f"LAN mode: open http://<this PC's IP>:{port}/?token={svc.ctx.settings.get().lan_token}")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(application, host=host, port=port, log_level="warning")


@app.command()
def window(port: int = 4242) -> None:
    """Open the compact view in an always-on-top window (a separate OS window; needs the [window] extra)."""
    try:
        import webview
    except ImportError:
        typer.echo("pip install -e .[window] first (pywebview)", err=True)
        raise typer.Exit(1) from None
    webview.create_window("d2bg", f"http://127.0.0.1:{port}/compact", width=380, height=640, on_top=True)
    webview.start()


@app.command()
def draft(
    enemy: Annotated[
        str, typer.Option(help="Enemy heroes, comma separated (aliases work: am, qop, wr).")
    ] = "",
    ally: Annotated[str, typer.Option(help="Your team's heroes.")] = "",
    ban: Annotated[str, typer.Option(help="Banned heroes.")] = "",
    bucket: Annotated[str | None, typer.Option(help="Rank bucket: 1-2, 3-4, 5-6, 7-8 or all.")] = None,
    n: int = 10,
) -> None:
    """Draft advice in the terminal."""
    from d2bg.context import AppContext
    from d2bg.draft.service import DraftRequest, analyze

    ctx = AppContext()
    heroes = ctx.data.heroes

    def ids(text: str) -> list[int]:
        found, unknown = heroes.parse_list(text)
        if unknown:
            typer.echo(f"unknown heroes: {', '.join(unknown)}", err=True)
        return [h.id for h in found]

    req = DraftRequest(allies=ids(ally), enemies=ids(enemy), bans=ids(ban), rank_bucket=bucket, n=n)
    res = analyze(ctx, req, ctx.settings.get())
    typer.echo(f"Bucket {res['bucket']} ({res['sample_matches']} matches, {res['source_week']})")
    if res["win"]:
        typer.echo(f"Win probability for your side: {res['win']['us']:.1%}")
    typer.echo("Suggested picks:")
    for c in res["suggestions"]:
        good = ", ".join(f"{heroes.name(g['hero'])} +{g['value']:.1f}" for g in c["why"]["good_against"])
        typer.echo(f"  {heroes.name(c['hero']):<22} {c['score']:+6.2f}  pos {c['positions']}  {good}")
    if res["bans"]:
        typer.echo("Ban: " + ", ".join(heroes.name(b["hero"]) for b in res["bans"][:5]))
    for rule in res["items"]:
        typer.echo(f"Items ({rule['reason']}): {', '.join(i['name'] for i in rule['items'])}")


@app.command()
def build(hero: str) -> None:
    """A hero's skill and item build from pro games on this patch."""
    from d2bg.builds.guide import build_text, hero_build
    from d2bg.context import AppContext

    ctx = AppContext()
    h = ctx.data.heroes.get(hero) or next(iter(ctx.data.heroes.search(hero, 1)), None)
    if h is None:
        typer.echo(f"no hero matches {hero!r}", err=True)
        raise typer.Exit(1)
    typer.echo(build_text(hero_build(ctx, h.id)))


def main() -> None:  # pragma: no cover - console entry point
    sys.exit(app())
