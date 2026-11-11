# Running the project in Wokwi (no hardware needed)

Wokwi officially supports the MFRC522 with six preset cards, so you can
demonstrate several students with only one or two real tags.

## Steps

1. Go to <https://wokwi.com/projects/new/esp32> (new ESP32 project).
2. **sketch.ino** tab: paste the contents of
   `../rfid-attendance-door.ino` — same file, nothing to edit.
3. **diagram.json** tab: replace everything with `diagram.json` from this folder.
4. Press the **+** (Add board) → **Library Manager**, or just paste
   `libraries.txt` contents — the green play button installs `MFRC522` and
   `ESP32Servo` automatically from `libraries.txt`.
5. Press ▶ to start. Wait for `System Ready`.
6. Click the MFRC522 on the canvas to open its card panel, choose a card, then
   press **Tap**.

If a wire is reported as an unknown pin, drag that connection by hand — Wokwi
renames ESP32 pins occasionally (`D5`, `D18`, `D21`, `D23`, `D19`, `3V3`, `5V`,
`GND.1`…).

## Preset cards and how they map to the roster

| Key | Card | UID | In roster? | Result |
|---|---|---|---|---|
| `b` | Blue | `01:02:03:04` | Alice Sharma (CS-01) | GRANTED, door unlocks |
| `g` | Green | `11:22:33:44` | Rohit Verma (CS-02) | GRANTED, door unlocks |
| `y` | Yellow | `55:66:77:88` | Sara Khan (CS-03) | GRANTED, door unlocks |
| `r` | Red | `AA:BB:CC:DD` | Imran Qureshi (CS-04) | GRANTED, door unlocks |
| `n` | NFC tag | `04:11:22:33:44:55:66` | no | **DENIED** — door stays locked |
| `k` | Key fob | `C0:FF:EE:99` | no | **DENIED** — door stays locked |

`t` taps the selected card. The NFC tag and key fob give you two unregistered
"fake" credentials for the rejection demo without touching the code.

## Demonstrating proxy detection in the simulator

Tap `b`, then `g`, then `y` within about five seconds (keyboard: `b`, `t`, `g`,
`t`, `y`, `t`). The third record is flagged:

```
         !! 3 different cards tapped within 5s - possible proxy attendance
[..] Sara Khan     CS-03 GRANTED  PRESENT  <<< PROXY SUSPECT
```

## Indicator LEDs

The diagram carries the same two LEDs as the real build, so the simulator shows the
same feedback as the bench:

| LED | Pin | Lights when |
|---|---|---|
| Green | **GPIO 26** | a card is accepted — 0.5 s pulse (`grantFlash()`) |
| Red | **GPIO 27** | a card is refused — 0.5 s flash (`denyFlash()`) |

Tap the NFC tag (`n`, then `t`) and you get the red flash with the door still shut; tap
`b` and the green one fires as the servo gives its two-pulse nudge.

Wokwi's LED has no series resistor, so it is drawn straight to the pin. The breadboard
version has a **220–330 Ω** resistor in each leg — same pins, same behaviour.

## Notes

- Wokwi's ESP32 has no real Wi-Fi by default. Leave `WIFI_SSID` empty and the
  sketch runs in offline mode: timestamps show as `T+42s` with `"src":"uptime"`.
  Use the **Wokwi IoT Gateway** if you want the cloud upload part to work.
- Write commands into the **Serial Monitor** input box, e.g.
  `sim DE AD BE EF`.
