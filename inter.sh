
SONG_NAME="inter"
yt-dlp -o "videos_debug/${SONG_NAME} Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  "https://www.youtube.com/watch?v=X9_HAQhdp_k&list=RDX9_HAQhdp_k&start_radio=1"

# 额外处理: 单独抽取另一个视频的音频
yt-dlp -o "videos_debug/inter_music Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  "https://www.youtube.com/watch?v=PDztCvdsv5g&list=RDPDztCvdsv5g&start_radio=1"


yt-dlp -o "videos_debug/inter_extra Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  "https://www.youtube.com/watch?v=uE7EOsmjB80"


ffmpeg -i "./videos_debug/inter_music Ori.mp4" \
  -vn -c:a flac -ar 48000 -sample_fmt s32 \
  "./audios/inter.flac"

# 分割视频
ffmpeg -i "./videos_debug/inter_extra Ori.mp4" \
  -ss 00:01:10 \
  -to 00:02:00 \
  -c copy \
  "./videos_debug/inter_extra.mp4"

# 分割视频
ffmpeg -i "./videos_debug/${SONG_NAME} Ori.mp4" \
  -ss 00:00:02 \
  -to 00:02:06 \
  -c copy \
  "./videos_debug/${SONG_NAME}.mp4"

SONG_NAME="inter"
ffmpeg -i "./videos_debug/inter.mp4" -vf "crop=1920:1080:320:0" -c:a copy "./videos_debug/${SONG_NAME} cut.mp4"

# 裁剪视频
ffmpeg -i "./videos_debug/inter_extra Ori.mp4" -vf "crop=1920:1080:320:0" -c:a copy "./videos_debug/inter_extra cut.mp4"

ffmpeg -i "./audios/inter.flac" -ss 00:00:16 -to 00:03:36 -c copy "./audios/inter_cut.flac"

# ### 合并2个视频
ffmpeg -i "./videos_debug/inter cut.mp4" \
  -i "./videos_debug/inter_extra.mp4" \
  -filter_complex "[0:v]format=yuv420p,setpts=PTS-STARTPTS[v0];[1:v]format=yuv420p,setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0[v]" \
  -map "[v]" \
  -c:v libx264 \
  -r 24 \
  -g 1 \
  -keyint_min 1 \
  -sc_threshold 0 \
  -preset medium \
  -crf 18 \
  "./videos_debug/inter_merged.mp4"


SONG_NAME="inter_merged"
rm -rf "input_frames" && mkdir -p "input_frames"
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vf "fps=30" "input_frames/%08d.png"
# 30->60
rm -rf "./output_frames" && mkdir -p "output_frames"
./rife-ncnn-vulkan -i "input_frames" -o "output_frames" -m models/rife-v4.6 -j 3:6:3

SONG_NAME="inter_merged"
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
  -c:v libx264 -crf 18 -preset medium \
  -pix_fmt yuv420p \
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark v2.mp4"