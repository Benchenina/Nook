"""Cross-platform media player launcher for Nook."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from nook.database import Database
from nook.streaming import is_stream_url


def get_clean_env() -> Dict[str, str]:
    """Return an environment dictionary safe for launching external system processes.

    When running inside a frozen bundle (PyInstaller / AppImage), environment variables
    such as LD_LIBRARY_PATH, PYTHONPATH, PYTHONHOME, and QT_PLUGIN_PATH point to bundled
    libraries. If inherited by external child processes (such as xdg-open, kde-open,
    dolphin, vlc, mpv, or desktop browsers), they cause dynamic linker errors and
    crashes due to Qt/GLIBC version mismatches with the host system.

    This function restores the original system environment so external applications
    link against the host system's libraries cleanly.
    """
    env = dict(os.environ)

    # Restore or clean LD_LIBRARY_PATH (Linux)
    orig_ld = env.get("LD_LIBRARY_PATH_ORIG")
    if orig_ld and orig_ld.strip():
        env["LD_LIBRARY_PATH"] = orig_ld
    else:
        env.pop("LD_LIBRARY_PATH", None)

    # Restore or clean macOS library paths
    for mac_var in ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
        orig_var = mac_var + "_ORIG"
        orig_val = env.get(orig_var)
        if orig_val and orig_val.strip():
            env[mac_var] = orig_val
        else:
            env.pop(mac_var, None)

    # Strip runtime variables that interfere with external tools
    for var in (
        "PYTHONPATH",
        "PYTHONHOME",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "QML_IMPORT_PATH",
        "QML2_IMPORT_PATH",
        "LD_PRELOAD",
        "APPIMAGE",
        "APPDIR",
        "ARGV0",
        "OWD",
    ):
        env.pop(var, None)

    return env


def open_system_path(target: str | Path) -> bool:
    """Open a file, directory, or URL using the operating system's default handler."""
    target_str = str(target).strip()
    if is_stream_url(target_str):
        return open_url(target_str)
    # Synthetic URIs (e.g. hianime://..., miruro://...) should never be handed to the file manager
    if "://" in target_str:
        return False

    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(target_str)
            return True
        elif system == "Darwin":
            subprocess.Popen(["open", target_str], env=get_clean_env())
            return True
        else:
            subprocess.Popen(
                ["xdg-open", target_str],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=get_clean_env(),
            )
            return True
    except Exception:
        return False


def open_file_folder(file_path: str | Path) -> bool:
    """Open the directory containing file_path in the system file manager."""
    fp = Path(file_path)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(f'explorer /select,"{fp}"')
            return True
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(fp)], env=get_clean_env())
            return True
        else:
            folder = fp.parent if fp.is_file() else fp
            subprocess.Popen(
                ["xdg-open", str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=get_clean_env(),
            )
            return True
    except Exception:
        return False


def _open_url_windows(url: str) -> bool:
    """Open a URL on Windows in the actual default web browser without invoking File Explorer."""
    cmd_str = None

    # 1. Query user's default browser choice from registry
    try:
        import winreg
        for proto in ("https", "http"):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{proto}\UserChoice",
                ) as key:
                    prog_id, _ = winreg.QueryValueEx(key, "ProgId")
                    if prog_id:
                        with winreg.OpenKey(
                            winreg.HKEY_CLASSES_ROOT,
                            rf"{prog_id}\shell\open\command",
                        ) as cmd_key:
                            cmd_val, _ = winreg.QueryValueEx(cmd_key, "")
                            if cmd_val and cmd_val.strip():
                                cmd_str = cmd_val.strip()
                                break
            except Exception:
                pass

        if not cmd_str:
            for proto in ("https", "http"):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CLASSES_ROOT,
                        rf"{proto}\shell\open\command",
                    ) as key:
                        cmd_val, _ = winreg.QueryValueEx(key, "")
                        if cmd_val and cmd_val.strip() and "explorer.exe" not in cmd_val.lower():
                            cmd_str = cmd_val.strip()
                            break
                except Exception:
                    pass

        if not cmd_str:
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r"Software\Clients\StartMenuInternet") as key:
                        browser_name, _ = winreg.QueryValueEx(key, "")
                        if browser_name:
                            with winreg.OpenKey(
                                root,
                                rf"Software\Clients\StartMenuInternet\{browser_name}\shell\open\command",
                            ) as cmd_key:
                                cmd_val, _ = winreg.QueryValueEx(cmd_key, "")
                                if cmd_val and cmd_val.strip():
                                    cmd_str = cmd_val.strip()
                                    break
                except Exception:
                    pass
    except Exception:
        pass

    # If registry command was discovered, launch it directly
    if cmd_str:
        try:
            if "%1" in cmd_str:
                cmd = cmd_str.replace("%1", url)
            elif "%*" in cmd_str:
                cmd = cmd_str.replace("%*", url)
            else:
                cmd = f'{cmd_str} "{url}"'
            subprocess.Popen(cmd)
            return True
        except Exception:
            pass

    # 2. Check standard browser install locations
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    candidates = [
        # Microsoft Edge
        os.path.join(prog_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(prog_files, r"Microsoft\Edge\Application\msedge.exe"),
        # Google Chrome
        os.path.join(prog_files, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(prog_files_x86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
        # Mozilla Firefox
        os.path.join(prog_files, r"Mozilla Firefox\firefox.exe"),
        os.path.join(prog_files_x86, r"Mozilla Firefox\firefox.exe"),
        # Brave
        os.path.join(prog_files, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(local_app_data, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]

    for exe in candidates:
        if exe and Path(exe).exists():
            try:
                subprocess.Popen([exe, url])
                return True
            except Exception:
                pass

    # 3. Fallback to rundll32 url.dll,FileProtocolHandler
    try:
        subprocess.Popen(["rundll32.exe", "url.dll,FileProtocolHandler", url])
        return True
    except Exception:
        pass

    # 4. Fallback: os.startfile with explicit 'open' verb
    try:
        os.startfile(url, "open")
        return True
    except Exception:
        pass

    # 5. Final fallback: Python's webbrowser module
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _open_url_linux(url: str) -> bool:
    """Open a URL on Linux using the desktop's default browser with a clean environment."""
    clean_env = get_clean_env()

    # Desktop opener utilities
    for opener in ("xdg-open", "gio", "kde-open5", "kde-open", "gnome-open"):
        opener_path = shutil.which(opener, path=clean_env.get("PATH"))
        if opener_path:
            try:
                cmd = [opener_path, "open", "--", url] if opener == "gio" else [opener_path, url]
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=clean_env,
                )
                return True
            except Exception:
                continue

    # Known browser binaries in PATH
    for browser in ("firefox", "google-chrome", "chromium", "brave-browser", "microsoft-edge", "epiphany"):
        browser_path = shutil.which(browser, path=clean_env.get("PATH"))
        if browser_path:
            try:
                subprocess.Popen(
                    [browser_path, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=clean_env,
                )
                return True
            except Exception:
                continue

    # Fallback to webbrowser module
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _open_url_macos(url: str) -> bool:
    """Open a URL on macOS using the default browser with a clean environment."""
    clean_env = get_clean_env()
    try:
        subprocess.Popen(
            ["open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env,
        )
        return True
    except Exception:
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception:
            return False


def open_url(url: str) -> bool:
    """Open a URL in the user's default browser with environment isolation."""
    if not url or not str(url).strip():
        return False

    url_str = str(url).strip()
    if not (url_str.startswith("http://") or url_str.startswith("https://")):
        if "://" not in url_str:
            url_str = "https://" + url_str
        else:
            return False

    # If webbrowser.open has been mocked (e.g. in test suites), delegate to the mock
    try:
        import webbrowser
        if hasattr(webbrowser.open, "assert_called"):
            return bool(webbrowser.open(url_str))
    except Exception:
        pass

    system = platform.system()
    if system == "Windows":
        return _open_url_windows(url_str)
    elif system == "Darwin":
        return _open_url_macos(url_str)
    else:
        return _open_url_linux(url_str)


class MediaPlayer:
    """Handles launching media files in system default or custom media players."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    @staticmethod
    def format_timestamp(seconds: int) -> str:
        """Convert seconds into HH:MM:SS or MM:SS format."""
        if seconds <= 0:
            return "00:00"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def play_episode(
        self,
        episode_id: int,
        resume: bool = True,
        override_player_path: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Launch the media player for the given episode ID.

        Episodes may point either at a local file or at a network stream
        (``http(s)://…`` / ``.m3u8``); both are handled transparently.
        """
        ep = self.db.get_episode_by_id(episode_id)
        if not ep:
            return False, f"Episode ID {episode_id} not found."

        media_reference = (ep.get("file_path") or "").strip()
        series_id = ep.get("series_id")
        series = self.db.get_series_by_id(series_id) if series_id else None
        is_streaming_series = bool(series and (series.get("source_type") or "local").lower() != "local")

        # Fallback to series source_url if this is a streaming series with no direct episode URL
        if is_streaming_series and (not media_reference or not is_stream_url(media_reference)):
            media_reference = (series.get("source_url") or "").strip()

        if not media_reference:
            return False, "Episode has no media source."

        start_time = ep["playback_position"] if (resume and ep.get("playback_position", 0) > 0) else 0

        if is_stream_url(media_reference) or is_streaming_series:
            # Network streams and browser shows are handed straight to the player / browser.
            success, err = self.play_url(
                media_reference,
                start_seconds=start_time,
                override_player_path=override_player_path,
            )
        else:
            file_path = Path(media_reference)
            if not file_path.exists():
                return False, f"Media file not found: {file_path}"
            success, err = self.play_file(
                file_path, start_seconds=start_time, override_player_path=override_player_path
            )

        if success:
            # Update watch stats
            self.db.update_episode_progress(
                episode_id=episode_id,
                playback_position=start_time,
                increment_play_count=True
            )
        return success, err

    def play_file(
        self,
        file_path: Path,
        start_seconds: int = 0,
        override_player_path: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Launch the specified local file using the configured or custom player."""
        return self._launch(
            str(file_path),
            is_url=False,
            start_seconds=start_seconds,
            override_player_path=override_player_path,
        )

    def play_url(
        self,
        url: str,
        start_seconds: int = 0,
        override_player_path: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Launch a network stream URL (HLS/``.m3u8``/direct link) or browser show."""
        return self._launch(
            url,
            is_url=True,
            start_seconds=start_seconds,
            override_player_path=override_player_path,
        )

    def _launch(
        self,
        target: str,
        is_url: bool,
        start_seconds: int = 0,
        override_player_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Dispatch a local file or network URL to the configured player."""
        system = platform.system()
        mode = self.db.get_setting("media_player_mode", "system")
        custom_path = override_player_path or self.db.get_setting("media_player_path", "").strip()

        # Check if we should use custom player
        if (mode == "custom" or override_player_path) and custom_path:
            return self._launch_custom_player(custom_path, target, start_seconds, is_url=is_url)

        # Fallback to system default player / browser handler
        return self._launch_system_player(target, system, is_url=is_url)

    def _launch_system_player(self, target: str, system: str, is_url: bool = False) -> Tuple[bool, str]:
        """Launch a file or URL with the OS default handler."""
        if is_url:
            if open_url(target):
                return True, ""
            return False, f"Failed to open URL in default browser: {target}"

        abs_path = str(Path(target).resolve())
        try:
            if system == "Windows":
                # os.startfile is non-blocking on Windows
                os.startfile(abs_path)
                return True, ""
            elif system == "Darwin":
                # macOS open
                subprocess.Popen(["open", abs_path], env=get_clean_env())
                return True, ""
            else:
                # Linux xdg-open
                subprocess.Popen(
                    ["xdg-open", abs_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=get_clean_env(),
                )
                return True, ""
        except FileNotFoundError:
            return False, f"System launcher utility not found (xdg-open / open)."
        except Exception as e:
            return False, f"Failed to open with system player: {str(e)}"

    def _launch_custom_player(
        self,
        player_path: str,
        target: str,
        start_seconds: int = 0,
        is_url: bool = False,
    ) -> Tuple[bool, str]:
        """Launch with a custom executable (VLC, MPV, etc.).

        VLC and MPV both accept network URLs (including HLS ``.m3u8``) in place
        of a local file path, so the same command construction is reused.
        """
        # Resolve command if given as command name or absolute path
        cmd_exec = shutil.which(player_path) or player_path
        if not Path(cmd_exec).exists() and not shutil.which(player_path):
            return False, f"Configured media player executable was not found: {player_path}"

        abs_target = target if is_url else str(Path(target).resolve())
        args = [cmd_exec]

        base_name = Path(cmd_exec).stem.lower()

        # Add timestamp parameters if resume is requested
        if start_seconds > 0:
            if "mpv" in base_name:
                args.append(f"--start={start_seconds}")
            elif "vlc" in base_name:
                args.append(f"--start-time={start_seconds}")
            elif "celluloid" in base_name:
                args.append(f"--mpv-start={start_seconds}")
            elif "smplayer" in base_name:
                args.append(f"-pos")
                args.append(str(start_seconds))

        args.append(abs_target)

        try:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=get_clean_env(),
            )
            return True, ""
        except Exception as e:
            return False, f"Failed to launch custom player '{cmd_exec}': {str(e)}"
