# someday
yt-dlp -o "videos_debug/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" "https://www.youtube.com/watch?v=pt2vZf5J5as&list=RDpt2vZf5J5as&start_radio=1"

yt-dlp -o "videos_debug/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4"  --write-sub \
        --write-auto-sub \
        --sub-lang "zh-CN,zh-TW,en" \
        --sub-format "srt" \
        "https://www.youtube.com/watch?v=pt2vZf5J5as&list=RDpt2vZf5J5as&start_radio=1"


 "Hala Madrid y Nada más" Real Madrid vs Manchester City UCL | Estadio Santiago Bernabéu 4K

https://www.youtube.com/watch?v=8LGpMYcVWfw&list=RD8LGpMYcVWfw&start_radio=1


yt-dlp -o "videos_debug/%(title)s.%(ext)s" -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
"https://www.youtube.com/watch?v=8LGpMYcVWfw&list=RD8LGpMYcVWfw&start_radio=1"