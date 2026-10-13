SONG_NAME="Someday"

# 提取高质量音频，生成 .flac 文件
SONG_NAME="Someday"
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"

# 待补充 python 脚本生成完美的字幕文件 .ass
python auto_sub.py -xxx

# 看下视频是多少帧 24/1
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1 "./videos_debug/${SONG_NAME}.mp4"

# 插帧准备工作操作
rm -rf input_frames
rm -rf output_frames
mkdir input_frames
mkdir output_frames
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vf "fps=30" "./input_frames/%08d.png"
# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 

# 有时候插帧的进度很慢，如果想看进度条，可以在另一个 terminal session 中打开
input_dir="input_frames" && input_file_count=$(find "$input_dir" -maxdepth 1 -type f | wc -l) && echo "$input_dir 中有 $input_file_count 个普通文件"
output_dir="output_frames" && output_file_count=$(find "$output_dir" -maxdepth 1 -type f | wc -l) && echo "$output_dir 中有 $output_file_count 个普通文件"

# 音频和视频合并, 同时升级成4k
ffmpeg -framerate 60 -i output_frames/%08d.png -i "./audios/${SONG_NAME}.flac" \
-vf "scale=3840:2160:flags=lanczos" \
-c:a copy \
-c:v libx264 -crf 20 -preset medium \
-pix_fmt yuv420p \
"./videos_debug/${SONG_NAME} 4K60FPS.mp4"

ffmpeg -i "./videos_debug/${SONG_NAME} 4K60FPS.mp4" -i "./adele-logo.png" \
-filter_complex "[1:v]scale=iw*0.10:-1[wm];[0:v]ass='./lyrics/${SONG_NAME}.ass'[sub];[sub][wm]overlay=15:15:format=auto" \
-c:a copy "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4"

SONG_NAME="Someday"
ffmpeg \
  -framerate 60 -i output_frames/%08d.png \
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
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark v2.mp4"