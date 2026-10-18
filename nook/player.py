"""Cross-platform media player launcher for Nook."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from nook.database import Database


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
        """Launch the media player for the given episode ID."""
        ep = self.db.get_episode_by_id(episode_id)
        if not ep:
            return False, f"Episode ID {episode_id} not found."

        file_path = Path(ep["file_path"])
        if not file_path.exists():
            return False, f"Media file not found: {file_path}"

        start_time = ep["playback_position"] if (resume and ep.get("playback_position", 0) > 0) else 0

        success, err = self.play_file(file_path, start_seconds=start_time, override_player_path=override_player_path)
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
        """Launch the specified file using the configured or custom player."""
        system = platform.system()
        mode = self.db.get_setting("media_player_mode", "system")
        custom_path = override_player_path or self.db.get_setting("media_player_path", "").strip()

        # Check if we should use custom player
        if (mode == "custom" or override_player_path) and custom_path:
            return self._launch_custom_player(custom_path, file_path, start_seconds)

        # Fallback to system default player
        return self._launch_system_player(file_path, system)

    def _launch_system_player(self, file_path: Path, system: str) -> Tuple[bool, str]:
        """Launch the file with OS default handler."""
        abs_path = str(file_path.resolve())
        try:
            if system == "Windows":
                # os.startfile is non-blocking on Windows
                os.startfile(abs_path)
                return True, ""
            elif system == "Darwin":
                # macOS open
                subprocess.Popen(["open", abs_path])
                return True, ""
            else:
                # Linux xdg-open
                subprocess.Popen(["xdg-open", abs_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, ""
        except FileNotFoundError:
            return False, f"System launcher utility not found (xdg-open / open)."
        except Exception as e:
            return False, f"Failed to open with system player: {str(e)}"

    def _launch_custom_player(
        self,
        player_path: str,
        file_path: Path,
        start_seconds: int = 0
    ) -> Tuple[bool, str]:
        """Launch with a custom executable (VLC, MPV, etc.)."""
        # Resolve command if given as command name or absolute path
        cmd_exec = shutil.which(player_path) or player_path
        if not Path(cmd_exec).exists() and not shutil.which(player_path):
            return False, f"Configured media player executable was not found: {player_path}"

        abs_file = str(file_path.resolve())
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

        args.append(abs_file)

        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, ""
        except Exception as e:
            return False, f"Failed to launch custom player '{cmd_exec}': {str(e)}"
