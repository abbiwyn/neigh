#!/usr/bin/env python3

from collections import deque
from datetime import datetime
import asyncio
import audioop
import concurrent
import json
import math
import os
import subprocess
import sys
import time
import wave

from buttplug.client import ButtplugClient
from buttplug.client import ButtplugClientWebsocketConnector
from playsound import playsound
from tensorflow.keras.models import load_model
import librosa
import numpy as np

from recorder import Recorder

# TODO: modularize config

# --------------------------------- Constants -------------------------------- #

CONFIG = {}

DEFAULT_CONFIG = {
    "model_path": "/Users/abbi/dev/jupyter/neigh-ml/saved_models/horse_2020.09.10-10.19.10.hdf5",
    "recordings_path": "/Users/abbi/dev/jupyter/neigh-ml/unprocessed_recordings",
    "server_path": "/Users/abbi/dev/intiface-cli-rs/target/release/intiface-cli",
    "record_vol": 160,
    "max_expected_vol": 1600,   
    "buildup_count": 20
}

# Audio settings
SAMPLE_RATE = 16000
FORMAT_WIDTH_IN_BYTES = 2
CHANNELS = 1

# Amount of frames (samples) to get each time we read data
CHUNK = 1024

# Seconds of silence that indicate end of speech
MAX_SILENCE_S = 0.1

# Seconds of audio to save before recording (to avoid cutting the start)
PREV_AUDIO_S = 0.2

# The time period over which to measure frequency, in seconds
# TODO: Clean this up, this makes no sense
SPEECH_FREQUENCY_SAMPLING_INTERVAL = 60


def predict_class(model, samples):
    labels = ['animal', 'other']

    mfccs = librosa.feature.mfcc(y=samples, sr=SAMPLE_RATE, n_mfcc=40)
    mfccs = np.reshape(mfccs, (1, 40, 32, 1))

    prediction = (model.predict(mfccs) > 0.5).astype("int32")[0][0]

    return sorted(labels)[prediction]

# --------------------------------- Vibration -------------------------------- #

def calculate_vibration_strength(curve, volume, recent_speech_count):
    return curve(volume, recent_speech_count)
    
def curve_linear(volume, recent_speech_count):
    return min(1.0, round(volume / CONFIG['max_expected_vol'], 2))

def curve_evil(volume, recent_speech_count):
    buildup_count = CONFIG['buildup_count']
    max_expected_vol = CONFIG['max_expected_vol']

    # Sigmoid function to make it extra evil
    vibration_strength = 1 / (1 + (math.e ** ((-volume / (max_expected_vol / 10)) + 5)))

    speech_frequency = recent_speech_count / SPEECH_FREQUENCY_SAMPLING_INTERVAL

    # 20 caws per minute to get max effect = freq = 0.333
    frequency_multiplier = min(1.0,
        speech_frequency /
            (buildup_count / SPEECH_FREQUENCY_SAMPLING_INTERVAL))

    vibration_strength = vibration_strength * (0.5 + (0.5 * frequency_multiplier))
    vibration_strength = round(vibration_strength, 2) # 2 decimal places = 100 values between 0 and 1

    return vibration_strength

# ------------------------------ Buttplug stuff ------------------------------ #

async def start_buttplug_server():
    await asyncio.create_subprocess_exec(CONFIG['server_path'], "--wsinsecureport", "12345")
    await asyncio.sleep(1) # Wait for the server to start up
    print('Buttplug server started')

async def init_buttplug_client():
    client = ButtplugClient("Neigh")
    connector = ButtplugClientWebsocketConnector("ws://127.0.0.1:12345")

    await client.connect(connector)
    await client.start_scanning()

    # Wait until we get a device
    while client.devices == {}:
        await asyncio.sleep(1)

    await client.stop_scanning()

    return client

# ----------------------------------- Misc ----------------------------------- #

async def load_config():
    global CONFIG

    config_path = 'config.json'

    if not os.path.exists(config_path):
        print('Neigh: Missing config.json, generating a new one')
    
        with open(config_path, 'w') as config:
            json.dump(DEFAULT_CONFIG, config, indent=4)

    with open(config_path) as config:
        CONFIG = json.load(config)

    print("Neigh: config.json loaded")

# This runs in the background and waits for things to be put in the queue
async def vibrate_worker(queue, bp_device):
    print('Starting vibrate worker')

    while True:
        vibration_strength = await queue.get()

        vibration_strength = max(0.1, vibration_strength)
        await bp_device.send_vibrate_cmd(vibration_strength)
        queue.task_done()
        await asyncio.sleep(1)
        await bp_device.send_stop_device_cmd()

# ------------------------------- Main function ------------------------------ #

async def main():
    await load_config()
    await start_buttplug_server()

    bp_client = await init_buttplug_client()
    bp_device = bp_client.devices[0] # Just get the first device

    queue = asyncio.Queue()
    asyncio.create_task(vibrate_worker(queue, bp_device))

    model = load_model(CONFIG['model_path'])
    speech_timestamps = []
    recorder = Recorder()

    print('Neigh: Listening...')

    while True:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(concurrent.futures.ThreadPoolExecutor(), recorder.listen_and_record, CONFIG['record_vol'], MAX_SILENCE_S, PREV_AUDIO_S)
        recorder.trim_or_pad(1.0)

        # Keras model expects an array of floats
        speech_floats = librosa.util.buf_to_float(recorder.get_bytes(), FORMAT_WIDTH_IN_BYTES)
        predicted_class = predict_class(model, speech_floats)

        if (predicted_class == 'animal'):
            volume = recorder.get_rms_volume()
            
            # Add timestamp
            speech_timestamps.append(datetime.now())
            
            # Remove old timestamps
            speech_timestamps = [ts for ts in speech_timestamps
                if (datetime.now() - ts).seconds < SPEECH_FREQUENCY_SAMPLING_INTERVAL]

            # Do fun stuff!
            vibration_strength = calculate_vibration_strength(curve_evil, volume, len(speech_timestamps))
            await queue.put(vibration_strength)
            
            print(f'Got animal sound, vol: {volume}, vibe: {vibration_strength}')
            # playsound('~/dev/soundfx/quake_hitsound.mp3')
            
        # Save recordings to help improve model
        epoch_time = int(time.time())
        filename = f'{CONFIG["recordings_path"]}/{predicted_class}/output_{epoch_time}.wav'
        recorder.write_wav(filename)

# Start program
asyncio.run(main())