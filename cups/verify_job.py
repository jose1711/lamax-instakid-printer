#!/usr/bin/env python3
"""Verify a job from rastertoinstakid: CRC8, structure; optionally render a preview.

Usage: verify_job.py job.bin [preview.pgm]
"""
import sys
from collections import Counter
def crc8(d):
    c=0
    for b in d:
        c^=b
        for _ in range(8): c=((c<<1)^7)&255 if c&128 else (c<<1)&255
    return c
buf=open(sys.argv[1],'rb').read(); o=0; fr=[]
while o<len(buf):
    assert buf[o:o+2]==b'\x51\x78', f"sync @ {o}"
    cmd=buf[o+2]; L=buf[o+4]|buf[o+5]<<8; d=buf[o+6:o+6+L]
    assert crc8(d)==buf[o+6+L] and buf[o+7+L]==0xff, f"crc/end @ {o}"
    fr.append((cmd,d)); o+=8+L
cnt=Counter(c for c,_ in fr)
print("frames:",len(fr),{hex(k):v for k,v in cnt.items()})
print("order:", ' '.join(f"{c:02x}" for c,_ in fr if c!=0xa2)[:120], "| A2 lines:",cnt[0xa2])
print("AF energy:", [int.from_bytes(d,'little') for c,d in fr if c==0xaf], "A1 feed:", [int.from_bytes(d,'little') for c,d in fr if c==0xa1])
if len(sys.argv)>2:
    lines=[d for c,d in fr if c==0xa2]
    px=bytearray()
    for ln in lines:
        for b in ln:
            for i in range(8): px.append(0 if (b>>i)&1 else 255)
    open(sys.argv[2],'wb').write(b'P5 384 %d 255\n'%len(lines)+bytes(px))
