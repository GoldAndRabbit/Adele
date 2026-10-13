yt-dlp -o "videos_debug/${SONG_NAME} Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  --write-subs --sub-langs "en,zh-Hans,zh-Hant,zh,en.*" \
  "https://www.youtube.com/watch?v=mjREZoRqTWM"

# v2 版本
SONG_NAME="Ribsv2"
ffmpeg -i "./videos_debug/Current Affairs Ori.mp4" \
  -ss 00:40:20 \
  -to 00:44:20 \
  -c copy \
  "./videos_debug/${SONG_NAME}.mp4"

  # 看下视频是多少帧 24/1
ffprobe -vrror -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1 "./videos_debug/${SONG_NAME}.mp4"

# 如果是 4k, 先降低到 1080p
# ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" \
#   -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
#   -c:a copy \
#   "./videos_debug/${SONG_NAME} 1080.mp4"

# 插帧准备工作操作
rm -rf input_frames && mkdir input_frames
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vf "fps=30" "./input_frames/%08d.png"
# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
rm -rf output_frames && mkdir output_frames
# ./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 


SONG_NAME="Ribsv2"
# 提取高质量音频，生成 .flac 文件
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"
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


ffmpeg -i "./post/${SONG_NAME} 4K60FPS Sub-WaterMark v2.mp4" \
  -ss 00:00:02 \
  -to 00:04:00 \
  -c copy \
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark v3.mp4"