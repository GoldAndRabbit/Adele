
SONG_NAME="bzrp"
yt-dlp -o "videos_debug/${SONG_NAME} Ori" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4" \
  "https://www.youtube.com/watch?v=fvQ7uaM554g"


ffmpeg -i "./videos_debug/${SONG_NAME} Ori.mp4" \
  -ss 00:00:16 \
  -to 00:04:10 \
  -c copy \
  "./videos_debug/${SONG_NAME}.mp4"