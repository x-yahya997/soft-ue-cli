"""Handle Unreal Editor startup recovery prompts."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO


SETTINGS_KEY = "startup_recovery_action"
VALID_ACTIONS = {"recover", "skip", "manual"}


@dataclass(frozen=True)
class StartupRecoveryPrompt:
    hwnd: int
    title: str
    text: str
    buttons: dict[str, int]


@dataclass(frozen=True)
class StartupRecoveryResult:
    action: str
    title: str
    remembered: bool = False
    saved: bool = False
    clicked_button: str | None = None


class StartupRecoveryBlocked(RuntimeError):
    """Raised when a recovery prompt needs a user choice but none is available."""

    def __init__(self, prompt: StartupRecoveryPrompt, message: str | None = None) -> None:
        self.prompt = prompt
        super().__init__(
            message
            or (
                "Unreal Editor is blocked by a startup recovery prompt. "
                "Choose whether to recover or skip the unsaved session, or rerun with "
                "--startup-recovery recover|skip|manual."
            )
        )


def _find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for directory in [current, *current.parents]:
        bridge_dir = directory / ".soft-ue-bridge"
        if any(directory.glob("*.uproject")) or (bridge_dir / "instance.json").exists():
            return directory

    return current


def startup_recovery_settings_path(project_root: Path | None = None) -> Path:
    root = _find_project_root(project_root)
    return root / ".soft-ue-bridge" / "settings.json"


def load_startup_recovery_action(project_root: Path | None = None) -> str | None:
    path = startup_recovery_settings_path(project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    action = data.get(SETTINGS_KEY)
    return action if action in VALID_ACTIONS else None


def save_startup_recovery_action(action: str, project_root: Path | None = None) -> None:
    normalized = _normalize_action(action)
    if normalized not in VALID_ACTIONS:
        raise ValueError(f"invalid startup recovery action: {action}")

    path = startup_recovery_settings_path(project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    data[SETTINGS_KEY] = normalized
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_action(action: str | None) -> str | None:
    if action is None:
        return None

    value = action.strip().lower().replace("_", "-")
    if value in {"r", "recover", "restore"}:
        return "recover"
    if value in {"s", "skip", "ignore", "discard", "dont", "don't", "do-not", "no"}:
        return "skip"
    if value in {"m", "manual", "user"}:
        return "manual"
    if value in {"ask", "remembered"}:
        return value
    return None


def _button_for_action(prompt: StartupRecoveryPrompt, action: str) -> tuple[str, int] | None:
    def is_negative(label: str) -> bool:
        return any(token in label for token in ("don't", "do not", "skip", "ignore", "discard", "cancel", "no"))

    buttons = [(label, hwnd, label.lower()) for label, hwnd in prompt.buttons.items()]

    if action == "recover":
        for label, hwnd, lower in buttons:
            if any(token in lower for token in ("recover", "restore", "yes")) and not is_negative(lower):
                return label, hwnd

    if action == "skip":
        for label, hwnd, lower in buttons:
            if any(token in lower for token in ("don't recover", "do not recover", "don't restore", "do not restore")):
                return label, hwnd
        for label, hwnd, lower in buttons:
            if any(token in lower for token in ("skip", "ignore", "discard")):
                return label, hwnd
        for label, hwnd, lower in buttons:
            if lower.strip("& ") == "no":
                return label, hwnd

    return None


def _ask_action(prompt: StartupRecoveryPrompt, input_fn: Callable[[str], str]) -> str:
    while True:
        answer = input_fn(
            f"Unreal Editor is showing a startup recovery prompt ({prompt.title}). "
            "Recover unsaved files, skip recovery, or choose manually? [r/s/m]: "
        )
        action = _normalize_action(answer)
        if action in VALID_ACTIONS:
            return action
        print("Please enter r, s, or m.", file=sys.stderr)


def _ask_remember(input_fn: Callable[[str], str]) -> bool:
    answer = input_fn("Remember this startup recovery choice for this project? [y/N]: ")
    return answer.strip().lower() in {"y", "yes"}


def handle_startup_recovery_prompt(
    requested_action: str | None = "ask",
    *,
    remember: bool | None = None,
    interactive: bool | None = None,
    prompt_provider: Callable[[], StartupRecoveryPrompt | None] | None = None,
    clicker: Callable[[int], None] | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> StartupRecoveryResult | None:
    provider = prompt_provider or detect_startup_recovery_prompt
    prompt = provider()
    if prompt is None:
        return None

    if interactive is None:
        interactive = sys.stdin.isatty()

    normalized_request = _normalize_action(requested_action)
    remembered = False
    saved = False
    stored_action = load_startup_recovery_action()

    if normalized_request == "ask":
        if stored_action:
            action = stored_action
            remembered = True
        elif interactive:
            action = _ask_action(prompt, input_fn)
            if remember is None:
                remember = _ask_remember(input_fn)
        else:
            raise StartupRecoveryBlocked(prompt)
    elif normalized_request == "remembered":
        if not stored_action:
            raise StartupRecoveryBlocked(
                prompt,
                "Unreal Editor is blocked by a startup recovery prompt, but no remembered "
                "startup recovery choice exists for this project.",
            )
        action = stored_action
        remembered = True
    elif normalized_request in VALID_ACTIONS:
        action = normalized_request
    else:
        raise ValueError(f"invalid startup recovery action: {requested_action}")

    if remember is True and not remembered:
        save_startup_recovery_action(action)
        saved = True

    if action == "manual":
        if output:
            print("Leaving Unreal Editor startup recovery prompt for manual user choice.", file=output)
        return StartupRecoveryResult(action=action, title=prompt.title, remembered=remembered, saved=saved)

    button = _button_for_action(prompt, action)
    if button is None:
        raise StartupRecoveryBlocked(
            prompt,
            f"Unreal Editor is blocked by a startup recovery prompt, but no {action} button was found.",
        )

    (clicker or _click_button)(button[1])
    if output:
        print(f"Handled Unreal startup recovery prompt with action '{action}'.", file=output)
    return StartupRecoveryResult(
        action=action,
        title=prompt.title,
        remembered=remembered,
        saved=saved,
        clicked_button=button[0],
    )


def detect_startup_recovery_prompt() -> StartupRecoveryPrompt | None:
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    def get_text(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def get_class(hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def child_controls(hwnd: int) -> tuple[list[str], dict[str, int]]:
        texts: list[str] = []
        buttons: dict[str, int] = {}

        enum_child_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum_child_proc
        def callback(child_hwnd, _lparam):
            text = get_text(child_hwnd)
            if text:
                texts.append(text)
                if get_class(child_hwnd).lower() == "button":
                    buttons[text] = int(child_hwnd)
            return True

        user32.EnumChildWindows(hwnd, callback, 0)
        return texts, buttons

    candidates: list[StartupRecoveryPrompt] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        title = get_text(hwnd)
        child_texts, buttons = child_controls(hwnd)
        blob = " ".join([title, *child_texts, *buttons.keys()]).lower()
        has_recovery_word = any(token in blob for token in ("recover", "restore"))
        has_session_context = any(token in blob for token in ("unreal", "asset", "session", "unsaved", "previous"))

        if has_recovery_word and has_session_context and buttons:
            candidates.append(
                StartupRecoveryPrompt(
                    hwnd=int(hwnd),
                    title=title or "Unreal Editor",
                    text="\n".join(child_texts),
                    buttons=buttons,
                )
            )
        return True

    user32.EnumWindows(callback, 0)
    return candidates[0] if candidates else None


def _click_button(hwnd: int) -> None:
    if os.name != "nt":
        raise RuntimeError("startup recovery prompt automation is only available on Windows")

    import ctypes

    BM_CLICK = 0x00F5
    ctypes.windll.user32.SendMessageW(hwnd, BM_CLICK, 0, 0)
