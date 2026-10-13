# 每次更新下 yt-dlp
pip install -U yt-dlp pysubs2 ffmpeg
SONG_NAME="milan"
yt-dlp -o "videos_debug/${SONG_NAME} Ori.mp4" \
  -f "bestvideo[ext=mp4][height<=2160]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  --merge-output-format mp4 \
  --write-subs --sub-langs "en,de" \
  "https://www.youtube.com/watch?v=_JzS_xmW7PU"

yt-dlp -o "videos_debug/${SONG_NAME} Song Ori.mp4" \
  -f "bestvideo[ext=mp4][height<=2160]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  --merge-output-format mp4 \
  --write-subs --sub-langs "en,de" \
  "https://www.youtube.com/watch?v=FnRC2S1BlzA"

SONG_NAME="milan"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:00:04 -to 00:00:12 -c copy "${SONG_NAME}0.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:00:38 -to 00:00:40 -c copy "${SONG_NAME}1.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:00:45 -to 00:01:04 -c copy "${SONG_NAME}2.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:01:08 -to 00:01:28 -c copy "${SONG_NAME}3.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:01:33 -to 00:01:55 -c copy "${SONG_NAME}4.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:01:58 -to 00:02:17 -c copy "${SONG_NAME}5.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:02:22 -to 00:02:38 -c copy "${SONG_NAME}6.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:02:43 -to 00:03:03 -c copy "${SONG_NAME}7.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:03:08 -to 00:03:28 -c copy "${SONG_NAME}8.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:03:32 -to 00:03:54 -c copy "${SONG_NAME}9.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:03:58 -to 00:04:18 -c copy "${SONG_NAME}10.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:04:22 -to 00:04:46 -c copy "${SONG_NAME}11.mp4"
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" -ss 00:00:25 -to 00:00:37 -c copy "${SONG_NAME}12.mp4"
ffmpeg -f concat -safe 0 -i "list.txt" -c copy "milan_merge.mp4"

# 如果不需要截断
mv "videos_debug/${SONG_NAME} Ori.mp4" "videos_debug/${SONG_NAME}.mp4" 


# 如果需要截断
ffmpeg -i "videos_debug/${SONG_NAME} Ori.mp4" \
  -ss 00:17:45 \
  -to 00:21:59 \
  -c copy \
  "./videos_debug/${SONG_NAME}.mp4"

# 转换初始歌词
python txt_to_ass.py "ori_lyrics/${SONG_NAME}.txt" -o "ori_lyrics/${SONG_NAME}.ass"

# 转换校准后的歌词到 ass
python srt2ass.py -i "ori_lyrics/${SONG_NAME}.srt" -o "lyrics/${SONG_NAME}.ass"

# 看下视频是多少帧 24/1
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1 "./videos_debug/${SONG_NAME}.mp4"

# 如果是 4k, 先降低到 1080p
ffmpeg -i "./videos_debug/${SONG_NAME} Ori.mp4" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
  -c:a copy \
  "./videos_debug/${SONG_NAME}.mp4"

# 生成高清图片
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" "/Users/gold/repos/GFPGAN/video/%08d.png"

# 先合成一下视频
ffmpeg -framerate 29 -i "sharp_frames/%08d.png" -c:v libx264 -pix_fmt yuv420p "./videos_debug/${SONG_NAME}_sharp.mp4"

# 插帧准备工作操作
rm -rf input_frames && mkdir input_frames
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}_sharp.mp4" -vf "fps=30" "./input_frames/%08d.png"
# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
rm -rf output_frames && mkdir output_frames
# ./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 
  
# 提取高质量音频，生成 .flac 文件
ffmpeg -i "videos_debug/${SONG_NAME} Song Ori.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"
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
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4"

ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"
ffmpeg \
  -i "./videos_debug/${SONG_NAME}.mp4" \
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
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4"

ffmpeg -i "./post/${SONG_NAME} 4K60FPS Sub-WaterMark.mp4" \
  -ss 00:00:04 \
  -to 00:04:03 \
  -c copy \
  "./post/${SONG_NAME} 4K60FPS Sub-WaterMark v3.mp4"