model_path = '/Users/abbi/dev/jupyter/neigh-ml/saved_models/horse_2020.09.10-10.19.10.hdf5'
recordings_path = '/Users/abbi/dev/jupyter/neigh-ml/unprocessed_recordings'

# Audio format settings
sample_rate = 16000
format_width_in_bytes = 2
channels = 1
data_type = 'int16'

# Minimum record volume
record_vol = 160

# Seconds of silence that indicate end of speech
max_silence_s = 0.1

# Seconds of audio to save before recording (to avoid cutting the start)
prev_audio_s = 0.2

# Factor applied to all vibrate commands, use to limit max vibration strength
vibrate_factor = 0.6
