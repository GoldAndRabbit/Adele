# 切割视频，提取想要的片段
ffmpeg -i adele.mkv -ss 00:51:23 -to 00:55:27 -c copy "Set Fire to the Rain Ori.mkv"
ffmpeg -i Lady.Gaga.The.Monster.Ball.Tour.At.Madison.Square.Garden.2011.1080p.BluRay.x264.DD5.1-FGT.mkv -ss 01:39:20 -to 01:44:16 -c copy "Bad Romance.mkv"

# 如果有字幕的时候可以提取字幕，没有的话需要单独生成字幕
ffmpeg -i "Set Fire to the Rain Ori.mkv" -map 0:s:0 "subtitles.srt"
# 转换 ass
ffmpeg -i subtitles.srt -vf "subtitles=subtitles.srt:force_style='PrimaryColour=&H00FFFF20,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=1'" "Set Fire to the Rain.ass"

# 截取字幕
ffmpeg -i "Bad Romance.srt" -ss 01:39:00 -to 01:44:16 -c copy "Bad Romance v2.srt"

# 提取高质量音频，生成 .flac 文件
ffmpeg -i "./videos_debug/One Day.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/One Day.flac"

# 待补充 python 脚本生成完美的字幕文件 .ass
python auto_sub.py -xxx

# 看下视频是多少帧 24/1
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1 "./videos_debug/One Day.mp4"

# 插帧准备工作操作
rm -rf input_frames
rm -rf output_frames
mkdir input_frames
mkdir output_frames
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/One Day.mp4" -vf "fps=30" "./input_frames/%08d.png"

# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 

# 有时候插帧的进度很慢，如果想看进度条，可以在另一个 terminal session 中打开
input_dir="input_frames" && input_file_count=$(find "$input_dir" -maxdepth 1 -type f | wc -l) && echo "$input_dir 中有 $input_file_count 个普通文件"
output_dir="output_frames" && output_file_count=$(find "$output_dir" -maxdepth 1 -type f | wc -l) && echo "$output_dir 中有 $output_file_count 个普通文件"

# 音频和视频合并, 同时升级成4k
ffmpeg -framerate 60 -i output_frames/%08d.png -i "./audios/One Day.flac" \
-vf "scale=3840:2160:flags=lanczos" \
-c:a copy \
-c:v libx264 -crf 20 -preset medium \
-pix_fmt yuv420p \
"./videos_debug/One Day 4K60FPS.mp4"

# 合并视频或者字幕
ffmpeg -i "./videos_debug/One Day 4K60FPS.mp4" -vf "ass=./lyrics/One Day.ass" -c:a copy "./post/One Day 4K60FPS Sub.mp4"

# 增加水印

ffmpeg -i "./videos_debug/One Day 4K60FPS.mp4" -i "./adele-logo.png" \
-filter_complex "[1:v]scale=iw*0.10:-1[wm];[0:v]ass='./lyrics/One Day.ass'[sub];[sub][wm]overlay=15:15:format=auto" \
-c:a copy "./post/One Day 4K60FPS Sub-WaterMark v2.mp4"