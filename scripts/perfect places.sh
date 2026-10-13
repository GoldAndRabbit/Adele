# Step1: 下载视频 from YouTube
# Lorde - Perfect Places (#MelodramaLIVE in Nova's Red Room -Optus)
SONG_NAME="Perfect Places"
yt-dlp -o "videos_debug/${SONG_NAME} Ori" \
    -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
    "https://www.youtube.com/watch?v=sLixbFHufAE&list=RDsLixbFHufAE&start_radio=1"

# Step2: (可选) 分割视频
# ffmpeg -i "./videos_debug/${SONG_NAME} Ori.mp4" \
#   -ss 00:00:35 \
#   -to 00:04:47 \
#   -c copy \
#   "./videos_debug/${SONG_NAME}.mp4"

# Step3: 提取高质量音频，生成 .flac 文件
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"

# Step4: 30帧插帧 + 60帧插帧
# 看下视频是多少帧 24/1
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1 "./videos_debug/${SONG_NAME}.mp4"
# 插帧准备工作操作
rm -rf input_frames_v2 && mkdir input_frames_v2
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vf "fps=30" "./input_frames_v2/%08d.png"
# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
rm -rf output_frames_v2 && mkdir output_frames_v2
./rife-ncnn-vulkan -i input_frames_v2 -o output_frames_v2 -m models/rife-v4.6 -j 3:6:3 
# (可选) 有时候插帧的进度很慢，如果想看进度条，可以在另一个 terminal session 中打开
# input_dir="input_frames_v2" && input_file_count=$(find "$input_dir" -maxdepth 1 -type f | wc -l) && echo "$input_dir 中有 $input_file_count 个普通文件"
# output_dir="output_frames_v2" && output_file_count=$(find "$output_dir" -maxdepth 1 -type f | wc -l) && echo "$output_dir 中有 $output_file_count 个普通文件"

# Step5: 使用 demucs 分离出来人声音 + 用 Whisper 生成最初版本字幕
SONG_NAME="Perfect Places"
demucs "./audios/${SONG_NAME}.flac" -n htdemucs --two-stems=vocals -o "./separated" --jobs=4
whisper "separated/htdemucs/${SONG_NAME}/vocals.wav" \
  --language English \
  --model large-v3 \
  --temperature 0.0 \
  --best_of 5 \
  --beam_size 5 \
  --output_format srt \
  --output_dir "./tmp_lyrics/${SONG_NAME}" \
  --word_timestamps True

# Step6: 合并视频 + 音频 + 字幕 + 水印, 同时升级成 4k 版本
ffmpeg \
  -framerate 60 -i output_frames_v2/%08d.png \
  -i "./audios/${SONG_NAME}.flac" \
  -i "./adele-logo.png" \
  -filter_complex "\
    [0:v]scale=3840:2160:flags=lanczos[scaled]; \
    [scaled]ass='./lyrics/${SONG_NAME}.ass'[sub]; \
    [2:v]scale=iw*0.10:-1[wm]; \
    [sub][wm]overlay=15:15:format=auto" \
  -c:a copy \
  -c:v libx264 -crf 20 -preset medium \
  -pix_fmt yuv420p \
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4"
