# FLUX 3 Image Klein 本地封面试验

目标是用一张演出原帧制作无字母图，检查人物还原和舞台构图，再决定是否接入封面设计页。当前机器为 M4 Pro、48 GiB 统一内存。模型文件放在外置盘，项目 Python 与 MFLUX Python 分开。

## 推理与缓存

采用蒸馏版 Klein，默认 16 步。首轮用 MFLUX 格式的预量化权重，省去下载 BF16 再转换及同时保留两份权重的开销。Q4 用于验证流程和构图。若人物五官或笔触不理想，再用相同原帧、提示词、分辨率和 seed 对照 Q8。量化位数对本机速度和画质的影响需要实测。

- 文生图调用 `mflux-generate-flux3`，适用于构图草案。
- 人物编辑调用 `mflux-generate-flux3-edit --image-paths 原帧`。主帧决定姿态、人数、机位和服装。
- 多参考编辑复用同一入口，第一张给主构图，其后给同场人物细节，提示词明确每张的作用。MFLUX 支持 1 至 10 张，首轮对照只加一张。
- 服务接入方案为单 GPU 队列、同时运行一个作业。模型缓存按来源、修订和量化版本区分。结果缓存另计，键包含模型版本、参考图有序内容哈希、提示词、seed、尺寸和步数。相同请求复用已有结果。服务端保存耗时、参数及母图，页面可从母图派生四种发布版本。首轮通过本地 CLI 验证，服务与 UI 属于后续接入。

该 Q4 仓库使用 BFL 的参数名，MFLUX 0.24 使用 diffusers 风格的名称。首次下载后执行一次仓内转换脚本，保留 Q4 压缩行及其量化参数，调整末层调制顺序和 VAE 注意力投影形状。原始权重、转换缓存各占约 6 GB。再次推理可直接使用转换目录。[上游参数映射](https://github.com/huggingface/diffusers/blob/main/src/diffusers/loaders/single_file_utils.py)

## 首轮对照

用《Royals》的半身原片帧（1067.4072 秒）作为主参考，两张都用 1024 × 576、16 步、同一 seed。第二张增加同场侧面原帧（994.4072 秒）作人物参考。逐张看脸部轮廓、眼神、麦克风位置、衣服及舞台光色，再检查 3:4 中央裁切和肩部标题空间。若只有单张成功，保留它及失败记录。

## 本机复现

从项目根目录运行。外置盘挂载点为 `/Volumes/harddisk_5T`。

```sh
test -d /Volumes/harddisk_5T/adele-workflow || exit 1
export UV_CACHE_DIR=/Volumes/harddisk_5T/adele-workflow/work/uv-cache
export HF_HOME=/Volumes/harddisk_5T/adele-workflow/work/flux3/hf
uv venv --python 3.12 work/local-flux3/venv
uv pip install --python work/local-flux3/venv/bin/python 'mflux==0.24.0'
model_dir=/Volumes/harddisk_5T/adele-workflow/work/flux3/models/klein-mlx-4bit
hf download vanch007/FLUX.3-Image-Klein-mlx-4bit \
  --revision 6a19398f6e22d2c6ff3d6a5ac64b9ad210ec5e0c --local-dir "$model_dir"
source_dir=$model_dir
model_dir="${source_dir}-mflux024"
work/local-flux3/venv/bin/python workflow/prepare_flux3_klein_q4.py "$source_dir" "$model_dir"
export HF_HUB_OFFLINE=1 MLX_MAX_OPS_PER_BUFFER=12 MLX_MAX_MB_PER_BUFFER=64
refs=work/local-flux3/references
mkdir -p "$refs"
work/local-flux3/venv/bin/python - <<'PYTHON'
from pathlib import Path
from PIL import Image

source = Path("posts/grammys_2014/02_royals/covers/ai/references")
for frame in ("ts-1067.4072", "ts-994.4072"):
    with Image.open(source / (frame + ".jpg")) as image:
        image.thumbnail((768, 432), Image.Resampling.LANCZOS)
        image.save(Path("work/local-flux3/references") / (frame + ".png"))
PYTHON
prompt='A full-bleed oil painting of the live performance in reference one. Keep the camera framing, the singer’s features, dark curly hair, white top, microphone and star-like stage lights. Her face is clear and naturally lit. Restrained brushwork follows the contours of her cheeks and clothing. Deep stage shadows retain color. Leave breathing room near the shoulders for later typography. Unlettered artwork.'
work/local-flux3/venv/bin/mflux-generate-flux3-edit \
  --model "$model_dir" --base-model flux3-image-klein --image-paths "$refs/ts-1067.4072.png" \
  --prompt "$prompt" --compute-precision float16 --width 1024 --height 576 --steps 16 --seed 42 \
  --metadata --output work/local-flux3/royals-single.png
work/local-flux3/venv/bin/mflux-generate-flux3-edit \
  --model "$model_dir" --base-model flux3-image-klein --image-paths "$refs/ts-1067.4072.png" "$refs/ts-994.4072.png" \
  --prompt "$prompt Use reference two only for the same singer’s facial features." \
  --compute-precision float16 --width 1024 --height 576 --steps 16 --seed 42 \
  --metadata --output work/local-flux3/royals-dual.png
```

## 来源

- [MFLUX 的 FLUX 3 实现、尺寸及步数](https://github.com/mflux-community/mflux/blob/main/src/mflux/models/flux3/README.md)
- [魔搭官方蒸馏原版](https://www.modelscope.cn/models/black-forest-labs/flux-3-image-klein)及[官方 ComfyUI 格式](https://www.modelscope.cn/models/black-forest-labs/flux-3-image-klein-comfy)
- [本次选用的社区 MFLUX Q4 转换及许可](https://huggingface.co/vanch007/FLUX.3-Image-Klein-mlx-4bit)
- [项目原片选帧策略](ai_cover_frame_selection.md)

## 2026-11-09 本机结果

魔搭能查到官方仓库。本机使用 ModelScope CLI 下载原版配置时收到 404。实际采用上面固定修订的社区 Q4，下载后逐文件校验，转换后检查了 transformer、文本编码器、VAE 的参数名。MLX GPU 运算和两次断网模式推理均通过。

直接输入 1920 × 1080 整帧时首次生成发生 Metal 超时。成功配置先把参考帧等比缩到 768 × 432，使用 float16 计算并限制每个 Metal 命令缓冲区的工作量。两个独立进程都输出了 1024 × 576 的无字母图。

| 《Royals》 | 端到端耗时 | 进程峰值内存占用（macOS footprint） | 结果 |
|---|---:|---:|---|
| 单参考 | 187.37 秒 | 8.62 GB | [母图](../../work/local-flux3/royals-single.png) |
| 半身主帧加侧脸参考 | 170.04 秒 | 9.42 GB | [母图](../../work/local-flux3/royals-dual.png) |

单参考首个采样步耗时约 67 秒，随后约 8 秒一步。双参考约 10 秒一步，整轮用时包含启动和首次运行开销，不能据此推算批量吞吐。两图的眉眼和轮廓仅有细微差异，白上衣、持麦位置和两侧逆光均接近主帧。画面右侧的手指和麦克风前的指节仍欠清晰。以 3:4 居中裁切时，脸部在安全区内，伸出的手会被截断。两张图适合评估横版人物母图；竖版若需保留完整手势，应另选构图。

## BF16 人物编辑复试

使用同款蒸馏 Klein 的未量化社区 MLX 转换，修订 `3152df56e42348e69b79b14e43ae5dcaa80dc523`。原厂 Hugging Face 权重对本机账号返回 403。下载文件逐一校验；图像 Transformer 的 359 个张量均为 BF16。复用仓内格式转换，并在 CPU 上重排张量。推理使用 MLX GPU 默认 BF16，输出元数据记录 quantize 为 null。

改选《Royals》约 19:30 的原片帧。暖色逆光，麦克风已放低，人物朝画面右侧看。1024 × 576、16 步、seed 42，实测 186.66 秒，macOS 进程峰值占用 17.26 GB。近侧眼睑和瞳孔清楚，远侧眼因侧脸角度仅露出一部分，持麦手仍有运动模糊。原帧与提示词也已改变，这一轮不能单独衡量量化精度对眼睛的影响。[参考帧](../../work/local-flux3/bf16-close/d1169-05.jpg) · [BF16 母图](../../work/local-flux3/royals-bf16.png) · [推理参数](../../work/local-flux3/royals-bf16.metadata.json)

## 每次试跑的交付

每张结果随附一张等尺寸并排预览，左侧为实际输入的主参考原片，右侧为生成结果。多参考编辑另外列出辅助参考路径。汇报 MFLUX 生成秒数、含进程启动及模型加载的端到端秒数、macOS 进程峰值内存，以及 MLX 自报的峰值。内存按十进制 GB 展示，两种峰值独立统计。首次下载和模型格式转换单独计时。

从仓库根目录运行，每次推理单独保存日志。为生成命令加上 `/usr/bin/time -l` 前缀和 `--metadata`，将标准输出和标准错误写入同一日志。出图后运行以下命令生成同名的 `.comparison.jpg` 和 `.run.json`，在聊天中展示对比图与测量值。

```sh
work/local-flux3/venv/bin/python workflow/local_cover_report.py \
  work/local-flux3/royals-bf16.png work/local-flux3/trial-bf16.log
```

## FIBO 2.0 Edit Turbo 对照

同一张《Royals》约 19:30 的参考帧、同一提示词、seed 42 和 1024 × 576 输出。使用 Bria 在魔搭发布的 BF16 文件，四个权重文件均核对了 Hugging Face 官方修订 `7b133d62d92e897f1468af0427a73cc41a03cb5d` 的 SHA-256。FIBO 使用 4 步整帧编辑，FLUX 使用 16 步。FIBO 的画面有更重的金色笔触，眼部和握麦手都更清晰，但新增手指饰物和背景细节，右上角仍保留电视台标。

FIBO 成功运行的模型生成时间为 70.27 秒，进程总耗时为 73.46 秒，macOS 进程峰值为 27.66 GB，MLX 峰值为 17.44 GB。此前从外置盘直接加载时，进程运行 20.55 秒后遇到 Metal 超时。成功运行前将权重暂存于内置 SSD，将 MLX_MAX_OPS_PER_BUFFER 和 MLX_MAX_MB_PER_BUFFER 分别设为 4 和 16。下载、复制和失败尝试另计。权重长期保存在外置盘，试验后清理内置盘暂存副本。

[并排对比](../../work/local-flux3/royals-flux-fibo.comparison.jpg) · [FIBO 全尺寸输出](../../work/local-flux3/royals-fibo2-turbo.png) · [单次测量记录](../../work/local-flux3/royals-fibo2-turbo.run.json)
