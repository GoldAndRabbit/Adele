ffmpeg -i "./videos_debug/The Angel v2 1080.mp4" -vn -y -acodec pcm_s16le -ar 44100 -ac 2 "./audios/The Angel.wav"

# 这是 work的
demucs "./audios/The Angel.wav" -n htdemucs --two-stems=vocals -o "./separated" --jobs=4

whisper "separated/htdemucs/The Angel/vocals.wav" \
  --language English \
  --model large-v3 \
  --temperature 0.0 \
  --best_of 5 \
  --beam_size 5 \
  --output_format srt \
  --output_dir ./tmp_lyrics \
  --word_timestamps True