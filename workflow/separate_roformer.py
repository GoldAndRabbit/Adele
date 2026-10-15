#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人声分离（Mel-Band RoFormer，KimberleyJensen 的 vocals 权重），比 demucs htdemucs 干净，现场录音尤其明显。

依赖独立环境 .venv-sep（torch + einops + rotary_embedding_torch ...），模型代码来自
third_party/mss（ZFTurbo/Music-Source-Separation-Training），权重 models/melband_roformer/MelBandRoformer.ckpt（HuggingFace）。

.venv-sep/bin/python workflow/separate_roformer.py audios/X.flac -o separated/roformer/X/vocals.wav
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MSS = ROOT / "third_party" / "mss"
CKPT = ROOT / "models" / "melband_roformer" / "MelBandRoformer.ckpt"
CONFIG = MSS / "configs" / "KimberleyJensen" / "config_vocals_mel_band_roformer_kj.yaml"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--device", default=None, help="mps / cpu，默认能用 mps 就用")
    a = p.parse_args()

    sys.path.insert(0, str(MSS))
    import librosa
    import numpy as np
    import soundfile as sf
    import torch
    from utils.model_utils import demix
    from utils.settings import get_model_from_config

    device = torch.device(a.device or ("mps" if torch.backends.mps.is_available() else "cpu"))
    model, config = get_model_from_config("mel_band_roformer", str(CONFIG))
    state = torch.load(str(CKPT), map_location="cpu", weights_only=False)
    model.load_state_dict(state.get("state_dict", state) if isinstance(state, dict) else state)
    model = model.to(device).eval()

    sr = config.audio.sample_rate
    mix, _ = librosa.load(a.audio, sr=sr, mono=False)
    if mix.ndim == 1:
        mix = np.stack([mix, mix])
    print(f"分离 {Path(a.audio).name}: {mix.shape[1] / sr:.1f}s @ {sr}Hz on {device}", flush=True)
    with torch.inference_mode():
        out = demix(config, model, torch.tensor(mix, dtype=torch.float32), device, "mel_band_roformer", pbar=True)
    vocals = out["vocals"] if isinstance(out, dict) else out
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    sf.write(a.output, vocals.T, sr, subtype="PCM_16")
    print(f"写入 {a.output}")


if __name__ == "__main__":
    main()
