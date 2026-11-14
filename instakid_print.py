#!/usr/bin/env python3
"""Print to a LAMAX InstaKid2 Plus over Bluetooth LE from Linux.

The camera's thermal printer speaks the "cat printer" protocol (GATT service
0xAE30), see docs/protocol.md.

Usage:
  instakid_print.py info                       connect and list GATT characteristics
  instakid_print.py print image.png [options]  print an image (scaled to 384 px wide)
  instakid_print.py replay writes.txt          resend a captured job (debugging)

Options for `print`:
  --density 1|2|3   light / medium (default) / dark
  --no-dither       threshold instead of Floyd-Steinberg
  --dry-run         only build the job and report its size

Global options:
  --name NAME       advertised BLE name (default: BQ95B)
  --address MAC     connect to this address instead of matching the name
  --timeout SEC     how long to wait for the camera to advertise (default 60)

Notes:
  * The camera accepts a single BLE client. Close the phone app (Fun Print) first.
  * It only advertises while switched on (keep the display awake) and not connected.
  * It is a dual-mode device; plain `bluetoothctl connect`/bleak try BR/EDR and fail
    with "Page Timeout". We force LE with org.bluez.Bearer.LE1.Connect (BlueZ >= 5.8x)
    and talk to GATT directly over D-Bus.
"""
import argparse
import asyncio
import os
import sys

DEFAULT_NAME = "BQ95B"
WIDTH = 384
LINE_BYTES = WIDTH // 8
CHAR_WRITE = "0000ae01-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "0000ae02-0000-1000-8000-00805f9b34fb"
ENERGY = {1: 10000, 2: 15000, 3: 20000}


def crc8(data: bytes) -> int:
    """CRC-8, polynomial 0x07, init 0."""
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def frame(cmd: int, data: bytes) -> bytes:
    """51 78 <cmd> 00 <len LE16> <data> <crc8(data)> FF"""
    return (bytes([0x51, 0x78, cmd, 0x00]) + len(data).to_bytes(2, "little")
            + data + bytes([crc8(data), 0xFF]))


def image_to_lines(path: str, dither: bool = True):
    """Convert an image to 48-byte raster lines (1 = black, LSB first)."""
    from PIL import Image, ImageOps
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = ImageOps.autocontrast(img.convert("L"))
    h = max(1, round(img.height * WIDTH / img.width))
    img = img.resize((WIDTH, h), Image.LANCZOS)
    img = img.convert("1", dither=Image.FLOYDSTEINBERG if dither else Image.NONE)
    px = img.load()
    lines = []
    for y in range(h):
        row = bytearray(LINE_BYTES)
        for x in range(WIDTH):
            if px[x, y] == 0:
                row[x // 8] |= 1 << (x % 8)
        lines.append(bytes(row))
    return lines


def build_job(lines, density: int = 2, feed: int = 48) -> bytes:
    out = [
        frame(0xA3, b"\x00"),
        frame(0xA4, b"\x34"),
        frame(0xA6, bytes.fromhex("aa551738445f5f5f44382c")),
        frame(0xAF, ENERGY[density].to_bytes(2, "little")),
        frame(0xBE, b"\x00"),
        frame(0xBD, b"\x0a"),
    ]
    out += [frame(0xA2, ln) for ln in lines]
    out += [
        frame(0xBD, b"\x0a"),
        frame(0xA1, feed.to_bytes(2, "little")),
        frame(0xA6, bytes.fromhex("aa55170000000000000017")),
        frame(0xA3, b"\x00"),
        frame(0xA3, b"\x00"),
    ]
    return b"".join(out)


async def run(action, job, name, address, timeout):
    from bleak import BleakScanner
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus

    found = {}
    seen = asyncio.Event()

    def cb(dev, adv):
        if (address and dev.address.upper() == address.upper()) or \
           (not address and (dev.name or adv.local_name) == name):
            found["addr"] = dev.address.upper()
            seen.set()

    print("Looking for the camera (switched on, not connected to the phone)...")
    async with BleakScanner(cb, bluez={"filters": {"Transport": "le"}}):
        await asyncio.wait_for(seen.wait(), timeout)
        print("Found", found["addr"], "- connecting (LE)...")
        bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        dpath = "/org/bluez/hci0/dev_" + found["addr"].replace(":", "_")
        intro = await bus.introspect("org.bluez", dpath)
        dobj = bus.get_proxy_object("org.bluez", dpath, intro)
        await dobj.get_interface("org.bluez.Bearer.LE1").call_connect()

    try:
        props = dobj.get_interface("org.freedesktop.DBus.Properties")
        for _ in range(100):
            if (await props.call_get("org.bluez.Device1", "ServicesResolved")).value:
                break
            await asyncio.sleep(0.1)
        omi = await bus.introspect("org.bluez", "/")
        om = bus.get_proxy_object("org.bluez", "/", omi).get_interface(
            "org.freedesktop.DBus.ObjectManager")
        chars = {}
        for path, ifs in (await om.call_get_managed_objects()).items():
            ch = ifs.get("org.bluez.GattCharacteristic1")
            if ch and path.startswith(dpath):
                chars[ch["UUID"].value] = (path, ch["Flags"].value)
        if action == "info":
            for u, (pth, fl) in sorted(chars.items()):
                print("CHAR", u, fl, "/".join(pth.rsplit("/", 2)[-2:]))
            return

        notes = []
        npath = chars[CHAR_NOTIFY][0]
        nint = await bus.introspect("org.bluez", npath)
        nobj = bus.get_proxy_object("org.bluez", npath, nint)
        nobj.get_interface("org.freedesktop.DBus.Properties").on_properties_changed(
            lambda i, ch, inv: notes.append(bytes(ch["Value"].value)) if "Value" in ch else None)
        await nobj.get_interface("org.bluez.GattCharacteristic1").call_start_notify()

        wpath = chars[CHAR_WRITE][0]
        wint = await bus.introspect("org.bluez", wpath)
        wch = bus.get_proxy_object("org.bluez", wpath, wint).get_interface(
            "org.bluez.GattCharacteristic1")
        fd, mtu = await wch.call_acquire_write({})
        chunk = min(max(mtu - 3, 20), 244)
        print(f"Sending {len(job)} bytes in {chunk}-byte writes (MTU {mtu})...")
        for i in range(0, len(job), chunk):
            os.write(fd, job[i:i + chunk])
            await asyncio.sleep(0.01)
        os.close(fd)
        await asyncio.sleep(4 + len(job) / 1024 * 0.15)   # let it finish printing
        for n in notes:
            print("notify", n.hex())
        print("Done.")
    finally:
        try:
            await dobj.get_interface("org.bluez.Bearer.LE1").call_disconnect()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--address")
    ap.add_argument("--timeout", type=float, default=60)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    r = sub.add_parser("replay")
    r.add_argument("writes", help="text file: '<frame> <hex>' per line")
    p = sub.add_parser("print")
    p.add_argument("image")
    p.add_argument("--density", type=int, choices=(1, 2, 3), default=2)
    p.add_argument("--no-dither", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    job = None
    if a.cmd == "replay":
        job = b"".join(bytes.fromhex(l.split()[1]) for l in open(a.writes) if len(l.split()) > 1)
    elif a.cmd == "print":
        lines = image_to_lines(a.image, not a.no_dither)
        job = build_job(lines, a.density)
        print(f"{len(lines)} lines, job {len(job)} bytes")
        if a.dry_run:
            return
    asyncio.run(run(a.cmd, job, a.name, a.address, a.timeout))


if __name__ == "__main__":
    sys.exit(main())
