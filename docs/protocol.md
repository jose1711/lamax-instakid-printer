# InstaKid2 Plus printing protocol

Reverse engineered from the BLE traffic of the vendor app (*Fun Print*, `com.fun.mxw`) captured
with an nRF Sniffer for Bluetooth LE, for interoperability. The printer belongs to the "cat
printer" family (GT01/MX-series); the camera is treated by the app as model `V5G` / variant
"chongcheng" and its advertised name `BQ95B` is mapped to `GT01`.

## Advertising

* Name `BQ95B`, 16-bit service UUID `0xAF30`, connectable, **public** address.
* Dual-mode device (BR/EDR + LE). BlueZ prefers BR/EDR for such devices, so a normal
  `Device1.Connect` fails with *Page Timeout*. Connect with `org.bluez.Bearer.LE1.Connect`.
* Single central only. While connected (e.g. to the phone) it stops advertising.
* Stops advertising after a while when idle; keep the camera's display awake.

## GATT

| Service | Characteristic | Properties | Use |
| --- | --- | --- | --- |
| `0xAE30` | `0xAE01` | write without response | **commands / data** (handle 0x0006 in the capture) |
| | `0xAE02` | notify | responses (handle 0x0008, CCCD 0x0009) |
| | `0xAE03` / `0xAE04` | write-nr / notify | unused by the app |
| | `0xAE05` | indicate | unused |
| | `0xAE10` | read, write | unused |
| `0xAE3A` | `0xAE3B` / `0xAE3C` | write-nr / notify | unused |

ATT MTU 512 is negotiated; the app writes 504-byte chunks. We use 244 bytes with a 10 ms gap.
No flow control is needed: acknowledgements (`51 78 A3 00 01 00 00 00 FF`) arrive on `AE02` but
are not waited for.

## Frame

```
51 78 | cmd | 00 | len (LE16) | data[len] | crc8(data) | FF
```

CRC-8: polynomial `0x07`, init `0`, no reflection, over `data` only. Frames may be
concatenated freely in a write stream and split at arbitrary byte positions.

## Print job

```
A3 00                              status / sync
A4 34                              (constant in all captures, meaning unknown)
A6 aa551738445f5f5f44382c          (11-byte constant, meaning unknown)
AF <energy LE16>                   density: 10000 / 15000 / 20000
BE 00                              (unknown)
BD 0a                              (unknown)
A2 <48 bytes>  x N                 one raster line each
BD 0a
A1 <feed LE16>                     paper feed, app uses 0x0030 (48 lines)
A6 aa55170000000000000017          (end marker?)
A3 00
A3 00
```

Raster: 384 dots (48 bytes) per line, **1 = black**, **least significant bit first** (the
left-most pixel is bit 0 of the first byte). The height is arbitrary (tested up to a few
hundred lines). Before a job the app also sends `A8 00` and `BB 01` and at some points
`BC …`; none of them is needed for printing.

Notifications seen on `AE02`: `A3` acknowledgements, and after the job `AE …` / `A4 …` status
frames (`51 78 AE 01 01 00 00 00 FF`, `51 78 A4 01 01 00 01 07 FF`), likely paper/battery state
(not decoded).

## Capturing it yourself

The vendor app is a uni-app (JavaScript) bundle; the framing and job layout above are visible
in its source and were confirmed on the air. To sniff on the air:

1. Use an nRF52840 dongle with Nordic's *nRF Sniffer for Bluetooth LE* firmware.
2. Start `tools/nrf_follow.py <camera address> out.pcap 300` **before** the phone connects.
3. Print something from the app, then analyse with
   `tshark -r out.pcap -Y 'btatt.opcode==0x52' -T fields -e frame.number -e btatt.value`.

Android HCI snoop logs of recent Samsung phones do not contain ATT payloads (they are
truncated), so an over-the-air sniffer was needed.
