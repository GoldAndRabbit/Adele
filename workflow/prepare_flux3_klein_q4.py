"""Adapt the vanch007 FLUX.3 Klein MLX export to MFLUX 0.24's saved layout."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

import mlx.core as mx


def transformer_key(key):
    # MFLUX uses diffusers names. Apply identical renames to packed rows and scales.
    for source, target in (
        ("ref_time_in.", "target_timestep_embedder."),
        ("time_in.", "timestep_embedder."),
        ("final_layer.image.adaLN_modulation.1.", "norm_out.linear."),
        ("final_layer.image.linear.", "proj_out."),
        ("content_mode_blocks.", "mode_blocks."),
        ("single_blocks.", "single_transformer_blocks."),
        ("txt_in.", "context_embedder."),
        ("emb_in.", "x_embedders."),
    ):
        if key.startswith(source):
            key = target + key[len(source):]
            break
    for source, target in (
        (".in_layer.", ".linear_1."), (".out_layer.", ".linear_2."),
        (".lin.", ".linear."), (".q_proj.", ".attn.to_q."),
        (".k_proj.", ".attn.to_k."), (".v_proj.", ".attn.to_v."),
        (".attn_out.", ".attn.to_out."), (".mlp_in.", ".ff.linear_in."),
        (".mlp_out.", ".ff.linear_out."), (".norm.query_norm.scale", ".attn.norm_q.weight"),
        (".norm.key_norm.scale", ".attn.norm_k.weight"),
    ):
        key = key.replace(source, target)
    return key


def convert(source, dest):
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        out = Path(tmp) / "model"
        for component in ("transformer", "vae", "text_encoder"):
            folder = out / component
            folder.mkdir(parents=True)
            original = source / component
            index_file = original / "model.safetensors.index.json"
            index = json.loads(index_file.read_text())
            renamed = {}
            total_bytes = 0
            if component == "transformer" and "ref_time_in.in_layer.weight" not in index["weight_map"]:
                raise ValueError("Expected the BFL-named distilled transformer")
            for shard in sorted(set(index["weight_map"].values())):
                weights, metadata = mx.load(str(original / shard), return_metadata=True)
                result = {}
                for key, value in weights.items():
                    name = key
                    if component == "transformer":
                        name = transformer_key(key)
                        if name.startswith("norm_out.linear."):
                            # BFL stores shift then scale. MFLUX expects scale then shift.
                            a, b = mx.split(value, 2, axis=0)
                            value = mx.concatenate([b, a], axis=0)
                    elif component == "vae" and ".attentions." in key and value.ndim == 4:
                        if value.shape[-2:] != (1, 1):
                            raise ValueError(f"Unexpected attention projection shape for {key}")
                        value = value[:, :, 0, 0]
                    elif component == "text_encoder" and key.startswith("layers.") and int(key.split(".")[1]) >= 32:
                        continue
                    if name in renamed:
                        raise ValueError(f"Duplicate parameter {name}")
                    total_bytes += value.nbytes
                    result[name] = value
                    renamed[name] = shard
                mx.save_safetensors(str(folder / shard), result, metadata=metadata)
            index["weight_map"] = renamed
            index["metadata"] = {"total_size": total_bytes}
            (folder / index_file.name).write_text(json.dumps(index, indent=2))
            for file in original.iterdir():
                if file.is_file() and file != index_file and file.suffix != ".safetensors":
                    shutil.copy2(file, folder / file.name)
        for file in source.iterdir():
            if file.is_file():
                shutil.copy2(file, out / file.name)
        out.rename(dest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    args = parser.parse_args()
    # Conversion only reshapes and reorders stored tensors. Keep this I/O off Metal.
    with mx.stream(mx.cpu):
        convert(args.source, args.dest)
