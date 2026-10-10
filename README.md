# FS2105SE amplifier control for ESPHome

Prototype external component for an ESP32 rotary encoder controller connected to an Audiocom AMP2105A amplifier. Controls the amplifier over I2C; the Audiocom board continues handling Dante/audio. No I2S wiring, audio streaming, factory initialization, EQ changes, or reset commands.

**Not hardware tested.** ESPHome 2026.9.1 configuration/code generation and C++ header checks pass; simulated-bus driver tests pass. A full ESP32 firmware build was attempted but the build environment failed during ESP-IDF component discovery (`psutil.NoSuchProcess`), before firmware compilation. Compile on your ESPHome installation before flashing. GitHub CI is included to perform that build when uploaded.

## Features

- Linked master volume for left/right/woofer, adjustable limits, 0.1875 dB hardware steps.
- Encoder example uses approximately 1 dB per detent (0.9375 dB).
- Short press toggles mute across all three channels; turning while muted changes the level for unmute.
- Startup is **unmuted at approximately -40 dB** when control is enabled. No initial mute command. The amplifier can already be playing during the boot delay.
- Real register feedback for all three channel volumes and mute, refreshed every 5 seconds and after commands.
- Connection diagnostic, differing channel settings indication, readable status, manual refresh and explicit write-fault reset.
- Wi-Fi normally off; hold the encoder button for 5 seconds for an update access point.
- Authenticated offline web UI and browser firmware uploads. No router or Home Assistant required.
- Optional single-WS2812 status LED package.

## Install

Use ESPHome 2026.9.1 or later; this version is the validation target. Extract the project and keep `components/fs2105/` beside `amp-controller.yaml`. In Home Assistant's ESPHome add-on this normally means the component folder is `/config/esphome/components/fs2105/`.

1. Copy `secrets.example.yaml` to `secrets.yaml` and replace all three example passwords. If you already have a secrets file, merge the three entries instead of replacing it.
2. Choose your actual ESP32 board and edit the five pin substitutions. The supplied example is a **classic ESP32 DevKit/WROOM**, not an ESP32-C3/S3 pinout.
3. Keep `enable_control: false` for the first run. This allows reads only, including from UI/encoder requests. Confirm the amplifier identity, wiring and bus access first.
4. Validate, compile and flash over USB initially:

```sh
esphome config amp-controller.yaml
esphome run amp-controller.yaml
```

5. Once the checks below pass, change `enable_control: true` and flash again. The device will set the startup volume and unmute after its boot delay and first successful register snapshot.

No potentiometer is used. Reverse `pin_a` and `pin_b` if rotation is backwards. Adjust the rotary encoder `resolution` (1, 2 or 4) to suit your encoder.

## Wiring: example ESP32 DevKit

| Connection | ESP32 example |
| --- | --- |
| AMP2105A J3 pin 1 GND | GND |
| J3 pin 2 SDA | GPIO21 |
| J3 pin 3 SCL | GPIO22 |
| Encoder A / B | GPIO32 / GPIO33 |
| Encoder common | GND |
| Encoder push switch | GPIO25 to GND |

Use GPIO numbers, not header positions. Confirm J3 pin 1 orientation on the actual PCB. The supplied AMP2105A schematic shows 3.3 V I2C pullups. J3 does not supply power; the amplifier needs its normal supply. Do not use a 5 V-powered encoder module that pulls its outputs up to 5 V. An ESP32 with Wi-Fi has a different power budget from the earlier RP2040 estimate; verify supply capacity for the chosen board and radio operation.

### Shared I2C bus: resolve this before connection/use

The supplied schematic also connects the amplifier I2C bus to the Audiocom FPGA/controller. This component does **not** implement multi-master arbitration. Even polling is bus traffic. Confirm with Audiocom that the existing controller releases the bus, or use their recommended isolation/control arrangement. Closing configuration software and waiting 10 seconds do not prove bus ownership. Feedback can observe register changes between samples; that does not make concurrent masters safe.

The exact fitted IC must match the FS2105SE register map supplied by Audiocom. DEVID `0x2019` alone does not establish compatibility with all FS2105 variants. An address or identity mismatch prevents all writes. Default 7-bit address is `0x68`; documented alternatives are `0x69`, `0x6A`, `0x6B`. Change `address:` only after identifying the correct one. An unconnected amplifier should report `No chip response`; this is expected.

## Controls and feedback semantics

| Entity | Meaning |
| --- | --- |
| Master Volume | Writes the same attenuation to all three channels; displayed value is **left-channel readback**. |
| Left / Right / Woofer Volume Readback | Actual volume-register attenuation, not an audio-level meter, SPL or output power. |
| Mute | On only when **all three channels** have their mute bits set. A partial mute reports Off and Channel Settings Differ reports On. |
| Amplifier Connected | Most recent ID + all monitored registers were read successfully; not proof of audio, network or speaker health. |
| Channel Settings Differ | Channel volume codes differ, or only some channels are muted. Last valid sample. |
| Amplifier Status | Boot wait, read-only mode, ready, differing settings, communication failure or latched write fault. |

Feedback polling never restores an old volume. An encoder movement starts from a fresh left-channel read and then links all three channels again. Mute/volume commands use read-modify-write and verification. Polling cannot provide an atomic snapshot if another writer changes registers during reads.

On read failure, numerical feedback becomes NaN/unavailable and Connected becomes Off. Boolean feedback retains its last valid sample and must be interpreted with Connected. No commands are queued during outages. Read failures can recover on a later poll. Write/readback failures latch further writes off; inspect wiring/bus ownership, then use Clear Amplifier Write Fault. Clearing does not replay any command or restart startup initialization.

All-channel writes are sequential, not atomic: a bus failure may leave unequal channel settings. No automatic mute is attempted on a broken bus, and no safe muted state is guaranteed. No volume persistence or flash writes; reboot reapplies the configured startup only once after the first successful snapshot. If startup fails part-way through, it is not retried automatically. Rebooting only the amplifier can restore its factory settings; this driver does not detect every such reset.

`apply_startup: false` preserves the amplifier's existing volume/mute at startup. `enable_control: false` prevents **all** configuration writes. Neither option changes the factory firmware's own startup behavior.

## Wireless updates without a network

1. Compile the new firmware on your ESPHome machine. Save the OTA `.bin` file to your laptop or phone before going offline.
2. Hold the encoder button for at least 5 seconds, then release. Long holds do not toggle mute.
3. Join **Audiocom Maintenance** using your configured password. Accept the phone's request to stay on a Wi-Fi network without internet.
4. Open `http://192.168.4.1/` and log in as `admin` with your web password. UI assets are embedded, so no internet is needed to render it.
5. Use the OTA upload section with `firmware.bin` / `firmware.ota.bin`, **not** `firmware.factory.bin`. The device reboots after flashing, switches Wi-Fi off again and applies startup behavior.

The AP stays enabled until reboot or the Disable Maintenance Wi-Fi web button is pressed; there is no timer that could interrupt an upload. Firmware uploads/reboots temporarily interrupt encoder control, while the amplifier may keep playing at its existing setting. USB is the recovery route if Wi-Fi/button access fails. Avoid reflashing during live audio use.

## Optional Home Assistant

Add a station SSID/password beneath the existing `wifi:` block and set `enable_on_boot: true` if you want normal network availability. Keep `reboot_timeout: 0s`. Add:

```yaml
api:
  encryption:
    key: !secret api_encryption_key
  reboot_timeout: 0s
```

Generate a fresh API encryption key. Local encoder control continues without a network or API client. With Wi-Fi left off until maintenance, HA entities are only reachable during maintenance, and HA must have a network path to the ESP32; its standalone AP is not your home LAN.

## Optional RGB status

Add this to the main YAML after editing the LED pin in `rgb-status.yaml`:

```yaml
packages:
  rgb: !include rgb-status.yaml
```

The package controls one WS2812 at 5% brightness: red = disconnected/booting/write fault; purple = all channels muted; green/yellow/orange = left-channel attenuation ranges. It displays **readback**, even in read-only mode. It does not indicate audio level or clipping. It cannot directly use the LEDs on a separate RP2040-Matrix board.

## Register scope

Register definitions derive from the FS2105SE Datasheet V1.1 supplied for this project; the supplier PDF is not redistributed here.

| Register | Use |
| --- | --- |
| 0x03 | DEVID must equal 0x2019; 16-bit big-endian reads |
| 0x30 | DACCTRL mute mask 0x1110; fade mask 0x2220 (fade enabled only when applying startup) |
| 0x39 / 0x3A / 0x3B | L/R/woofer volume bits 15:7, preserving bits 6:0 |

`dB = (code - 511) * 0.1875`. Software limits round inward to representable codes; with the default -80 dB lower limit, the actual minimum is -79.875 dB. Startup -40 dB becomes -39.9375 dB. Limits constrain this controller's writes, not other writers or factory startup.

Temperature, clipping, overcurrent, signal meters, EQ and power-state controls are intentionally not guessed. Those can be added after confirming the exact silicon and status-register semantics, especially any read-to-clear flags.

## Development checks

```sh
python tests/test_driver.py  # g++ required, simulated register bus
esphome config amp-controller.yaml
esphome compile amp-controller.yaml
```

The test compiles the production driver against an isolated fake bus and checks read-only operation, chip ID rejection, unmuted startup, preservation of unrelated bits, bounds, mute, feedback, partial failures and recovery. It is not a substitute for hardware validation. CI builds both the base and optional RGB configurations using placeholder secrets; no usable firmware binary is published.

Primary ESPHome documentation:
- https://esphome.io/components/external_components/
- https://esphome.io/components/wifi/
- https://esphome.io/components/ota/web_server/
- https://esphome.io/components/sensor/rotary_encoder/
