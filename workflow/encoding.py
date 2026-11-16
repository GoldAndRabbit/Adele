"""The only video encoder presets used by final rendering."""
DEFAULT_ENCODER = "hevc_hw"
ENCODERS = {
    "x264": ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-profile:v", "high", "-level", "5.2"],
    "h264_hw": ["-c:v", "h264_videotoolbox", "-b:v", "50M", "-maxrate", "70M", "-bufsize", "100M", "-profile:v", "high", "-level", "5.2"],
    "hevc_hw": ["-c:v", "hevc_videotoolbox", "-b:v", "35M", "-maxrate", "50M", "-bufsize", "70M", "-profile:v", "main", "-tag:v", "hvc1"],
}
