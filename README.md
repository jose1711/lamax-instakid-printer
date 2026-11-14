# lamax-instakid-printer

Use the built-in thermal printer of the **LAMAX InstaKid2 Plus** (AI) children's camera as a
normal printer from Linux — from the command line, or as a **CUPS** printer (LibreOffice,
browsers, `lp`, ...).

> Unofficial. Not affiliated with LAMAX. The protocol was worked out by observing the BLE
> traffic of the vendor's phone app for interoperability, see [docs/protocol.md](docs/protocol.md).

## How it works

The camera's USB-C port only offers charging and an SD card reader (mass storage), there is
no printer interface. Printing happens over **Bluetooth LE**: the camera advertises as
`BQ95B` and exposes the well-known "cat printer" GATT service `0xAE30`. A print job is a
stream of small checksummed frames carrying a 384-pixel-wide 1-bit raster.

This repository contains:

| Path | What |
| --- | --- |
| `instakid_print.py` | Python CLI: print an image, list GATT characteristics |
| `cups/rastertoinstakid.c` | CUPS raster filter (dithering, trimming, protocol framing) |
| `cups/instakid` | CUPS backend (`instakid://BQ95B`), sends the job over BLE |
| `cups/instakid2.ppd` | printer description: 203 dpi, 48 mm wide, density/dither options |
| `cups/verify_job.py` | check a generated job (CRC, structure) and render a preview |
| `tools/nrf_follow.py` | capture a connection with an nRF Sniffer for Bluetooth LE |
| `docs/protocol.md` | the protocol, as far as it is understood |

## Requirements

* Linux with **BlueZ ≥ 5.80** (needs `org.bluez.Bearer.LE1`; developed on 5.88)
* Python 3.10+ with `bleak`, `dbus-fast`, `Pillow` (`pacman -S python-bleak python-pillow`)
* For CUPS: `cups`, `cups-filters`, `gcc`, `libcups` headers

## Quick start (CLI)

1. Switch the camera on, close the vendor app (**Fun Print**) / disconnect the phone, keep the
   camera's display awake (it only advertises while idle and not connected).
2. ```
   ./instakid_print.py print examples/test.png
   ./instakid_print.py print photo.jpg --density 3
   ./instakid_print.py info
   ```

Images are scaled to 384 px width and dithered (Floyd–Steinberg unless `--no-dither`).

## CUPS

```
make
sudo make install
sudo make add-printer          # lpadmin -p InstaKid2 -v instakid://BQ95B -P ... (media 48x50mm)
lp -d InstaKid2 -o fit-to-page examples/test.png
```

Options (PPD, `lp -o`): `Density=Light|Medium|Dark`, `Dither=FloydSteinberg|Threshold`, `Oversize=FitContent|Crop`,
`TrimBlank=True|False`, `Feed=0|24|48|96`, `PageSize=48x30mm|48x50mm|48x75mm|48x100mm|48x150mm`
or a custom length with a fixed 48 mm width.

Tips:

* The paper is only 48 mm wide. Set your document to that width — in LibreOffice Writer:
  *Format → Page Style → Page*, paper format *User*, width 48 mm, small margins. A text document
  left on A4 is scaled down to fit (see below), so the text becomes tiny.
* Pages wider than the paper (e.g. an image viewer printing on A4) are automatically cropped to
  their printed area and scaled to the paper width (`Oversize=FitContent`, default; `Crop` keeps
  only the left 48 mm). Blank rows at both ends are trimmed.
* For images `-o fit-to-page` also works. For text try `-o cpi=15` (default is 10 cpi, ~24 columns).
* The backend runs as root (mode 0700, standard for CUPS backends). If the camera is off or
  busy it returns `CUPS_BACKEND_RETRY`, so the job stays queued and is retried.

## Troubleshooting

* **Nothing found / `TimeoutError`**: the camera must be on, advertising and not connected to
  any other device (phone!). Check with `bluetoothctl scan on` for a device named `BQ95B`.
* **`Page Timeout` / `br-connection-page-timeout`**: you are using a client that connects with
  BR/EDR. Use this tool, or in `bluetoothctl`: `menu le` → `connect <address>`.
* **Job prints blank**: the document page is larger than the paper, see the tip above.
* The phone cannot find the camera while your PC is connected to it. The tools disconnect when
  they finish; after a crash run `bluetoothctl disconnect <address>`.

## Status

Tested with a LAMAX InstaKid2 Plus AI only: images, text, PDF/LibreOffice through CUPS.
Untested: multi-page jobs, copies, cancelling a job, battery/paper status, other firmware.
Contributions and reports from other InstaKid models are welcome.

## License

MIT, see [LICENSE](LICENSE).
