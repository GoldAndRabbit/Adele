SONG_NAME="Clearblue"
yt-dlp -o "videos_debug/Current Affairs Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  --write-subs --sub-langs "en,de" \
  "https://www.bilibili.com/video/BV1ugK6z8EMu/?spm_id_from=333.337.search-card.all.click&vd_source=ee132e30a5bbafb545b4d26d3df73e7d"


SONG_NAME="Clearblue"
ffmpeg -i "./videos_debug/Current Affairs Ori.mp4" \
  -ss 00:24:36 \
  -to 00:26:39 \
  -c copy \
  "./videos_debug/${SONG_NAME}.mp4"


SONG_NAME="Clearblue"
# 插帧准备工作操作
rm -rf input_frames && mkdir input_frames
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vf "fps=30" "./input_frames/%08d.png"
# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
rm -rf output_frames && mkdir output_frames
# ./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 

# 提取高质量音频，生成 .flac 文件
SONG_NAME="Clearblue"
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
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4"


SONG_NAME="Clearblue"
ffmpeg -i "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4" \
  -ss 00:00:02 \
  -to 00:02:03 \
  -c copy \
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark v3.mp4"