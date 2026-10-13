SONG_NAME="YNWA_standard"

ffmpeg -i "./videos_debug/${SONG_NAME}.mp4" -vn -c:a flac -ar 48000 -sample_fmt s32 "./audios/${SONG_NAME}.flac"

# 这是 work的
demucs "./audios/${SONG_NAME}.flac" -n htdemucs --two-stems=vocals -o "./separated" --jobs=4

whisper "separated/htdemucs/${SONG_NAME}/vocals.wav" \
  --language English \
  --model large-v3 \
  --temperature 0.0 \
  --best_of 5 \
  --beam_size 5 \
  --output_format srt \
  --output_dir "tmp_lyrics/${SONG_NAME}" \
  --word_timestamps True