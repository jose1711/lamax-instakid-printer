#!/usr/bin/env python3
"""Capture a BLE connection of one device with an nRF Sniffer for Bluetooth LE.

The stock extcap plugin cannot select a device without Wireshark's toolbar, so
this drives Nordic's SnifferAPI directly and writes a pcap (DLT 272, Nordic BLE
sniffer) that Wireshark/tshark can read.

Start it BEFORE the phone app connects to the camera, so the CONNECT_IND is seen.

  tools/nrf_follow.py AA:BB:CC:DD:EE:FF out.pcap 300 [--random] [--port /dev/ttyACM1]

Requires Nordic's "nRF Sniffer for Bluetooth LE" host package (SnifferAPI), by
default expected in /usr/lib/nrf-sniffer-ble/pymodule.

Then e.g.:  tshark -r out.pcap -Y 'btatt.opcode==0x52' -T fields \\
                   -e frame.number -e btatt.handle -e btatt.value
"""
import argparse
import sys
import time

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("address", help="device address, e.g. AA:BB:CC:DD:EE:FF")
ap.add_argument("out", help="output pcap")
ap.add_argument("seconds", type=int, nargs="?", default=300)
ap.add_argument("--random", action="store_true", help="address type is random (default public)")
ap.add_argument("--port", default="/dev/ttyACM1")
ap.add_argument("--pymodule", default="/usr/lib/nrf-sniffer-ble/pymodule")
a = ap.parse_args()

sys.path.insert(0, a.pymodule)
from SnifferAPI import Devices, Pcap, Sniffer  # noqa: E402

out = open(a.out, "wb", 0)
out.write(Pcap.get_global_header())
n = {"p": 0}


def new_packet(note):
    pk = note.msg["packet"]
    out.write(Pcap.create_packet(bytes([pk.boardId] + pk.getList()), pk.time))
    n["p"] += 1


s = Sniffer.Sniffer(a.port, 1000000)
s.subscribe("NEW_BLE_PACKET", new_packet)
s.setAdvHopSequence([37, 38, 39])
s.setSupportedProtocolVersion(3)
s.getFirmwareVersion()
s.getTimestamp()
s.start()
print("sniffer firmware", s.swversion, flush=True)

addr = [int(x, 16) for x in a.address.split(":")] + [1 if a.random else 0]
dev = Devices.Device(address=addr, name='""', RSSI=0)
s.addDevice(dev)
s.follow(dev, False, False, False)
print("following", a.address, "for", a.seconds, "s - now connect with the phone app", flush=True)

t = time.time()
while time.time() - t < a.seconds:
    time.sleep(1)
print("packets:", n["p"])
s.doExit()
out.close()
