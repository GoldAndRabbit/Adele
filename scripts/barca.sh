
SONG_NAME="Barca"
yt-dlp -o "videos_debug/${SONG_NAME} Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  "https://www.youtube.com/watch?v=QaM6oQwyj1c&list=RDQaM6oQwyj1c&start_radio=1&t=30s"

# 分割视频
ffmpeg -i "./videos_debug/${SONG_NAME} Ori.mp4" \
  -ss 00:00:09 \
  -to 00:01:52 \
  -c copy \
  "./videos_debug/${SONG_NAME}.mp4"

# 提取高质量音频，生成 .flac 文件
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"

# 看下视频是多少帧 24/1
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1 "./videos_debug/${SONG_NAME}.mp4"

# 如果是 4k, 先降低到 1080p
# ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" \
#   -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
#   -c:a copy \
#   "./videos_debug/${SONG_NAME} 1080.mp4"

# 插帧准备工作操作
rm -rf input_frames && mkdir input_frames
# 第一步如果是 24/25 fps，先用 ffmpeg 最快最搞到 30 fps
ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vf "fps=30" "./input_frames/%08d.png"

# 超分处理
input_dir="input_frames"
output_dir="sp_input_frames"
rm -rf "$output_dir" && mkdir -p "$output_dir"
total_files=$(ls "$input_dir" | wc -l)
processed=0
echo "开始超分 $total_files 张图片, 需要等很长时间, 去干点别的事情"
for file in "$input_dir"/*; do
    filename=$(basename "$file")
    ./realesrgan-ncnn-vulkan -i "$file" -o "$output_dir/${filename%.*}.png" -n realesrgan-x4plus -f png >/dev/null 2>&1
    # 更新进度条
    processed=$((processed + 1))
    percent=$((processed * 100 / total_files))
    printf "\r进度: [%-50s] %d%%" "$(printf '#%.0s' $(seq 1 $((percent / 2))))" "$percent"
done
echo -e "\n处理完成！"

# rm -rf sp_input_frames && mkdir sp_input_frames
# ./realesrgan-ncnn-vulkan -i input_frames -o sp_input_frames -n realesrgan-x4plus -f png
# ./realesrgan-ncnn-vulkan -i 00002759.png -o 00002759v2.png -n realesrgan-x4plus -f png

# ffmpeg -i 00002759.png -vf "eq=brightness=0.15:contrast=1.3" 00002759_hi.png
# input_dir="input_frames"
# output_dir="input_frames_bright"
# mkdir -p "$output_dir"
# # 遍历所有图片文件（支持 jpg/jpeg/png 等）
# for img in "$input_dir"/*.*; do
#   if [ -f "$img" ]; then
#     # 获取文件名和扩展名
#     filename=$(basename "$img")
#     extension="${filename##*.}"
#     filename="${filename%.*}"
#     # 应用滤镜并输出到新目录
#     ffmpeg -i "$img" -vf "eq=brightness=0.15:contrast=1.3" "$output_dir/${filename}.$extension"
#   fi
# done

# 正式插帧 每次对原始帧数 x2, 比如我们已经有了 30FPS 的，现在要, 30->60 rife-ncnn-vulkan
rm -rf output_frames && mkdir output_frames
# ./rife-ncnn-vulkan -i input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 
./rife-ncnn-vulkan -i sp_input_frames -o output_frames -m models/rife-v4.6 -j 3:6:3 

# rm -rf output_frames_v2 && mkdir output_frames_v2
# ./rife-ncnn-vulkan -i output_frames -o output_frames_v2 -m models/rife-v4.6 -j 3:6:3 


# 有时候插帧的进度很慢，如果想看进度条，可以在另一个 terminal session 中打开
input_dir="input_frames" && input_file_count=$(find "$input_dir" -maxdepth 1 -type f | wc -l) && echo "$input_dir 中有 $input_file_count 个普通文件"
sp_input_dir="sp_input_frames" && input_file_count=$(find "$sp_input_dir" -maxdepth 1 -type f | wc -l) && echo "$sp_input_dir 中有 $input_file_count 个普通文件"
output_dir="output_frames" && output_file_count=$(find "$output_dir" -maxdepth 1 -type f | wc -l) && echo "$output_dir 中有 $output_file_count 个普通文件"
output_dir_v2="output_frames_v2" && output_file_count=$(find "$output_dir_v2" -maxdepth 1 -type f | wc -l) && echo "$output_dir_v2 中有 $output_file_count 个普通文件"


SONG_NAME="Barca"
# 音频和视频合并, 同时升级成4k
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
