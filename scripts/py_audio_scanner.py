#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import numpy as np
import sounddevice as sd


def detect_audio_devices():
    """
    Find and list every audio device, using sounddevice.
    """
    print("\n===== Audio devices (via sounddevice) =====\n")

    # the default devices
    default_input = sd.default.device[0] if sd.default.device else None
    default_output = sd.default.device[1] if sd.default.device else None

    # what we find
    input_devices = []
    output_devices = []

    # walk every device
    devices = sd.query_devices()
    for i, dev_info in enumerate(devices):
        # print what it is
        print(f"Device {i}: {dev_info['name']}")
        print(f"  - input channels: {dev_info['max_input_channels']}")
        print(f"  - output channels: {dev_info['max_output_channels']}")
        print(f"  - default sample rate: {dev_info['default_samplerate']}")

        # mark the defaults
        if i == default_input:
            print("  - 🎤 the system default input")
        if i == default_output:
            print("  - 🔊 the system default output")

        # spot the inputs (microphones)
        if dev_info["max_input_channels"] > 0:
            input_devices.append((i, dev_info["name"]))
            if "USB" in dev_info["name"]:
                print("  - probably a USB microphone 🎤")

        # spot the outputs (speakers)
        if dev_info["max_output_channels"] > 0:
            output_devices.append((i, dev_info["name"]))
            if "Headphones" in dev_info["name"]:
                print("  - probably headphones 🎧")
            elif "USB" in dev_info["name"] and dev_info["max_output_channels"] > 0:
                print("  - probably a USB speaker 🔊")

        print("")

    # summarise
    print("\n===== Summary =====\n")

    print("Inputs (microphones):")
    for idx, name in input_devices:
        default_mark = " (default)" if idx == default_input else ""
        print(f"  - device {idx}: {name}{default_mark}")

    print("\nOutputs (speakers):")
    for idx, name in output_devices:
        default_mark = " (default)" if idx == default_output else ""
        print(f"  - device {idx}: {name}{default_mark}")

    # what to recommend
    print("\nRecommended:")

    # pick a microphone
    recommended_mic = None
    if default_input is not None:
        recommended_mic = (default_input, devices[default_input]["name"])
    elif input_devices:
        # prefer a USB device
        for idx, name in input_devices:
            if "USB" in name:
                recommended_mic = (idx, name)
                break
        if recommended_mic is None:
            recommended_mic = input_devices[0]

    # pick a speaker
    recommended_speaker = None
    if default_output is not None:
        recommended_speaker = (default_output, devices[default_output]["name"])
    elif output_devices:
        # prefer headphones
        for idx, name in output_devices:
            if "Headphones" in name:
                recommended_speaker = (idx, name)
                break
        if recommended_speaker is None:
            recommended_speaker = output_devices[0]

    if recommended_mic:
        print(f"  - microphone: device {recommended_mic[0]} ({recommended_mic[1]})")
    else:
        print("  - no usable microphone found")

    if recommended_speaker:
        print(
            f"  - speaker: device {recommended_speaker[0]} ({recommended_speaker[1]})"
        )
    else:
        print("  - no usable speaker found")

    print("\n===== Example sounddevice setup =====\n")

    if recommended_mic:
        print("# opening the microphone")
        print(f"input_device_id = {recommended_mic[0]}  # {recommended_mic[1]}")
        print("input_stream = sd.InputStream(")
        print("    samplerate=16000,")
        print("    channels=1,")
        print("    dtype=np.int16,")
        print("    blocksize=1024,")
        print(f"    device={recommended_mic[0]},")
        print("    callback=input_callback)")

    if recommended_speaker:
        print("\n# opening the speaker")
        print(
            f"output_device_id = {recommended_speaker[0]}  # {recommended_speaker[1]}"
        )
        print("output_stream = sd.OutputStream(")
        print("    samplerate=44100,")
        print("    channels=1,")
        print("    dtype=np.int16,")
        print("    blocksize=1024,")
        print(f"    device={recommended_speaker[0]},")
        print("    callback=output_callback)")

    print("\n===== Device test =====\n")

    # try the recommended devices
    if recommended_mic:
        print(f"Testing the microphone (device {recommended_mic[0]})...")
        try:
            sd.rec(
                int(1 * 16000),
                samplerate=16000,
                channels=1,
                device=recommended_mic[0],
                dtype=np.int16,
            )
            sd.wait()
            print("✓ microphone works")
        except Exception as e:
            print(f"✗ microphone test failed: {e}")

    if recommended_speaker:
        print(f"Testing the speaker (device {recommended_speaker[0]})...")
        try:
            # a 440Hz sine wave to play
            duration = 0.5
            sample_rate = 44100
            t = np.linspace(0, duration, int(sample_rate * duration))
            test_audio = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)

            sd.play(test_audio, samplerate=sample_rate, device=recommended_speaker[0])
            sd.wait()
            print("✓ speaker works")
        except Exception as e:
            print(f"✗ speaker test failed: {e}")

    return recommended_mic, recommended_speaker


if __name__ == "__main__":
    try:
        mic, speaker = detect_audio_devices()
        print("\nDone.")
    except Exception as e:
        print(f"Something went wrong: {e}")
