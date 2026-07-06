"""Command-line interface for near-iron-claw.

Subcommands:
    config   show resolved settings (key redacted)
    models   list model ids exposed by the gateway
    chat     run a chat completion (prompt via arg or stdin); --stream to stream
    verify   health-check the gateway + key, exit non-zero on failure

Add ``--json`` to any command for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from . import __version__
from .client import NearAIClient
from .config import Settings
from .errors import ConfigError, NearAIError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="near-iron-claw",
        description="Client for NEAR AI Cloud (hosted IronClaw), an OpenAI-compatible gateway.",
    )
    parser.add_argument("--version", action="version", version=f"near-iron-claw {__version__}")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON output")
    parser.add_argument("--env-file", default=None, help="path to a .env file (default: ./.env)")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="show resolved settings (secrets redacted)")
    sub.add_parser("models", help="list available model ids")
    sub.add_parser("verify", help="health-check gateway reachability and key validity")

    chat = sub.add_parser("chat", help="run a chat completion")
    chat.add_argument("prompt", nargs="?", help="user prompt (omit to read from stdin)")
    chat.add_argument("-m", "--model", default=None, help="model slug override")
    chat.add_argument("--system", default=None, help="optional system prompt")
    chat.add_argument("--max-tokens", type=int, default=None)
    chat.add_argument("--temperature", type=float, default=None)
    chat.add_argument("--stream", action="store_true", help="stream the response token-by-token")

    return parser


def _cmd_config(args: argparse.Namespace, settings: Settings) -> int:
    view = settings.redacted()
    if args.json:
        print(json.dumps(view, indent=2, sort_keys=True))
    else:
        for key, value in view.items():
            print(f"{key:>16}: {value}")
    return 0


def _cmd_models(args: argparse.Namespace, client: NearAIClient) -> int:
    models = client.list_models()
    if args.json:
        print(json.dumps({"models": models}, indent=2))
    else:
        for model in models:
            print(model)
    return 0


def _cmd_verify(args: argparse.Namespace, client: NearAIClient) -> int:
    result = client.verify()
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        def mark(ok):
            return "✅" if ok else "❌"
        print(f"{mark(result.gateway_reachable)} gateway reachable: {result.gateway_reachable}")
        key_line = "not checked (no key)" if result.key_valid is None else str(result.key_valid)
        print(f"{mark(result.key_valid is True)} key valid: {key_line}")
        if result.model_count is not None:
            print(f"   models available: {result.model_count}")
        print(f"   {result.detail}")
        for err in result.errors:
            print(f"   - {err}", file=sys.stderr)
    return 0 if result.ok else 1


def _cmd_chat(args: argparse.Namespace, client: NearAIClient) -> int:
    prompt = args.prompt if args.prompt is not None else sys.stdin.read().strip()
    if not prompt:
        print("error: no prompt provided (pass an argument or pipe via stdin)", file=sys.stderr)
        return 2

    messages: list[dict] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": prompt})

    kwargs = dict(model=args.model, max_tokens=args.max_tokens, temperature=args.temperature)

    if args.stream:  # --stream + --json is rejected in main(), so this is text output
        for piece in client.stream_chat(messages, **kwargs):
            sys.stdout.write(piece)
            sys.stdout.flush()
        sys.stdout.write("\n")
        return 0

    reply = client.chat(messages, **kwargs)
    if args.json:
        print(json.dumps({"model": args.model or client.settings.model, "reply": reply}, indent=2))
    else:
        print(reply)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Streaming emits raw text token-by-token; JSON needs the whole reply. Reject
    # the combination explicitly rather than silently dropping one of them.
    if getattr(args, "stream", False) and args.json:
        parser.error("--stream cannot be combined with --json")

    # A user-supplied --env-file that doesn't exist is almost certainly a typo;
    # fail loudly instead of silently falling back to defaults/process env.
    if args.env_file is not None and not os.path.isfile(args.env_file):
        parser.error(f"--env-file not found: {args.env_file}")

    settings = Settings.load(dotenv_path=args.env_file)

    try:
        if args.command == "config":
            return _cmd_config(args, settings)

        with NearAIClient(settings) as client:
            if args.command == "models":
                return _cmd_models(args, client)
            if args.command == "verify":
                return _cmd_verify(args, client)
            if args.command == "chat":
                return _cmd_chat(args, client)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except NearAIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
