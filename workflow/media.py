"""Basic media specification checks shared by final delivery."""
import json
import subprocess

def check_hires(path):
    """成品音轨必须是 FLAC 48kHz/24bit，否则 B 站不显示 Hi-Res无损。"""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=codec_name,sample_rate,bits_per_raw_sample", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    st = json.loads(out)["streams"][0]
    ok = st.get("codec_name") == "flac" and st.get("sample_rate") == "48000" and st.get("bits_per_raw_sample") == "24"
    if not ok:
        raise ValueError(f"音轨不是 FLAC 48kHz/24bit（{st}），B 站不会显示 Hi-Res无损")
    print("音轨检查: FLAC 48kHz/24bit ✓（Hi-Res无损）")
