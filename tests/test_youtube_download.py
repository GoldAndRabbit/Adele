import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workflow import youtube_download as yt


class YoutubeDownloadTests(unittest.TestCase):
    def test_video_and_restore_session_settings(self):
        with patch.object(yt, "ensure_provider") as check:
            args = yt.cli_args("https://youtu.be/test", proxy="http://127.0.0.1:7890", browser="chrome")
        check.assert_called_once()
        self.assertIn("youtube:player_client=default,mweb", args)
        self.assertIn("youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416", args)
        self.assertEqual(args[-4:], ["--proxy", "http://127.0.0.1:7890", "--cookies-from-browser", "chrome"])

    def test_other_hosts_do_not_depend_on_provider(self):
        with patch.object(yt, "ensure_provider") as check:
            self.assertEqual(yt.cli_args("https://www.bilibili.com/video/example"), [])
            self.assertEqual(yt.cli_args("https://youtube.com.example/video"), [])
        check.assert_not_called()

    def test_healthy_service_is_reused(self):
        with patch.object(yt, "version", return_value="2.0.2"), patch.object(yt, "_healthy", return_value=True), \
                patch.object(yt.subprocess, "Popen") as spawn:
            yt.ensure_provider()
        spawn.assert_not_called()

    def test_missing_service_starts_once_and_only_on_loopback(self):
        with tempfile.TemporaryDirectory() as t:
            server = Path(t) / "server"
            (server / "build").mkdir(parents=True)
            (server / "build/main.js").touch()
            child = Mock()
            with patch.dict(yt.os.environ, {"ADELE_BGUTIL_SERVER_DIR": str(server)}), \
                    patch.object(Path, "home", return_value=Path(t)), patch.object(yt, "version", return_value="2.0.2"), \
                    patch.object(yt.shutil, "which", return_value="/usr/bin/node"), \
                    patch.object(yt, "_healthy", side_effect=[False, False, True, True]), \
                    patch.object(yt.subprocess, "Popen", return_value=child) as spawn:
                yt.ensure_provider()
                yt.ensure_provider()
            spawn.assert_called_once()
            self.assertEqual(spawn.call_args.args[0][-4:], ["--host", "127.0.0.1", "--port", "4416"])
            child.terminate.assert_not_called()
