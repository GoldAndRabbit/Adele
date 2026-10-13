yt-dlp -o "videos/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" "https://www.youtube.com/watch?v=5gU277dBf8I&list=RD5gU277dBf8I&start_radio=1&ab_channel=LouisDunfordVEVO"

yt-dlp -o "videos/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4"  --write-sub \
        --write-auto-sub \
        --sub-lang "zh-CN,zh-TW,en" \
        --sub-format "srt" \
        "https://www.youtube.com/watch?v=pt2vZf5J5as&list=RDpt2vZf5J5as&start_radio=1&ab_channel=OneRepublicVEVO"



yt-dlp -o "videos/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4"  --write-sub \
        --write-auto-sub \
        --sub-lang "zh-CN,zh-TW,en" \
        --sub-format "srt" \
        "https://www.youtube.com/watch?v=8M1GeNrYDHI&list=RD8M1GeNrYDHI&start_radio=1"

yt-dlp -o "videos/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" --write-sub \
        --write-auto-sub \
        --sub-lang "zh-CN,zh-TW,en" \
        --sub-format "srt" \
        "https://www.youtube.com/watch?v=XqvKDCP5-xE&list=RDXqvKDCP5-xE&start_radio=1&ab_channel=Koolulam"

# yt-dlp -o "music/%(title)s.%(ext)s" -x --audio-format mp3 https://www.youtube.com/watch?v=Av6Zfj7h5ZY&ab_channel=smelly_p

#!/bin/bash

# 定义固定的列表文件路径
LIST_FILE="links.list"

# 检查列表文件是否存在
if [ ! -f "$LIST_FILE" ]; then
    echo "错误：文件 '$LIST_FILE' 不存在"
    exit 1
fi

# 创建视频目录（如果不存在）
mkdir -p videos

# 读取列表文件中的每一行并下载
while IFS= read -r line; do
    # 跳过空行
    if [ -z "$line" ]; then
        continue
    fi
    
    echo "正在下载: $line"
    yt-dlp -o "videos/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" "$line"
    
    # 检查下载是否成功
    if [ $? -eq 0 ]; then
        echo "✓ 下载完成"
    else
        echo "✗ 下载失败: $line"
    fi
    echo
done < "$LIST_FILE"

echo "所有下载任务已完成"