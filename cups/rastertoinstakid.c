/*
 * rastertoinstakid - CUPS raster filter for the LAMAX InstaKid2 Plus (BLE "BQ95B").
 *
 * Reads CUPS raster (8-bit gray W/SW/RGB or 1-bit K) and emits a print job in the
 * "cat printer" protocol (see docs/protocol.md):
 *
 *   frame = 51 78 <cmd> 00 <len LE16> <data> <crc8(data), poly 0x07> FF
 *   job   = A3 A4 A6 AF BE BD  A2 x N  BD A1 A6 A3 A3
 *   A2 line = 48 bytes (384 dots, 1 = black, LSB first)
 *
 * Options (PPD / lp -o):
 *   Density=Light|Medium|Dark   energy 10000/15000/20000
 *   Dither=FloydSteinberg|Threshold
 *   TrimBlank=True|False        drop blank rows at the end of a page
 *   Feed=<lines>                paper feed after printing (default 48)
 *
 * Build: gcc -O2 -Wall -o rastertoinstakid rastertoinstakid.c -lcups
 */

#include <cups/cups.h>
#include <cups/raster.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

#define WIDTH      384
#define LINE_BYTES (WIDTH / 8)

static unsigned char crc8(const unsigned char *d, size_t n)
{
  unsigned char c = 0;
  size_t i;
  int k;

  for (i = 0; i < n; i++)
  {
    c ^= d[i];
    for (k = 0; k < 8; k++)
      c = (c & 0x80) ? (unsigned char)((c << 1) ^ 0x07) : (unsigned char)(c << 1);
  }
  return c;
}

static void put_frame(unsigned char cmd, const unsigned char *d, unsigned len)
{
  unsigned char hdr[6] = { 0x51, 0x78, cmd, 0x00, (unsigned char)(len & 0xff),
                           (unsigned char)(len >> 8) };
  unsigned char tail[2];

  tail[0] = crc8(d, len);
  tail[1] = 0xff;
  fwrite(hdr, 1, sizeof(hdr), stdout);
  if (len)
    fwrite(d, 1, len, stdout);
  fwrite(tail, 1, 2, stdout);
}

static int truthy(const char *v, int def)
{
  if (!v)
    return def;
  return !(!strcasecmp(v, "false") || !strcasecmp(v, "no") || !strcasecmp(v, "off") ||
           !strcmp(v, "0"));
}

/* pixel brightness 0..255 (255 = white) from a raster row */
static int pixel_gray(const cups_page_header2_t *h, const unsigned char *row, unsigned x)
{
  if (h->cupsBitsPerColor == 1)
  {
    int bit = (row[x >> 3] >> (7 - (x & 7))) & 1;
    int black = (h->cupsColorSpace == CUPS_CSPACE_K) ? bit : !bit;
    return black ? 0 : 255;
  }
  if (h->cupsNumColors >= 3)
  {
    const unsigned char *p = row + (size_t)x * h->cupsNumColors;
    return (p[0] * 30 + p[1] * 59 + p[2] * 11) / 100;
  }
  {
    int v = row[(size_t)x * h->cupsNumColors];
    /* CUPS_CSPACE_K in 8 bits: 255 = black */
    return (h->cupsColorSpace == CUPS_CSPACE_K) ? 255 - v : v;
  }
}

static void emit_job(unsigned char *lines, unsigned nlines, int density, int feed)
{
  static const unsigned energy[4] = { 0, 10000, 15000, 20000 };
  unsigned char b[2];
  unsigned i;

  b[0] = 0x00;
  put_frame(0xA3, b, 1);
  b[0] = 0x34;
  put_frame(0xA4, b, 1);
  {
    static const unsigned char a6a[11] = { 0xaa, 0x55, 0x17, 0x38, 0x44, 0x5f,
                                           0x5f, 0x5f, 0x44, 0x38, 0x2c };
    put_frame(0xA6, a6a, sizeof(a6a));
  }
  b[0] = energy[density] & 0xff;
  b[1] = energy[density] >> 8;
  put_frame(0xAF, b, 2);
  b[0] = 0x00;
  put_frame(0xBE, b, 1);
  b[0] = 0x0a;
  put_frame(0xBD, b, 1);

  for (i = 0; i < nlines; i++)
    put_frame(0xA2, lines + (size_t)i * LINE_BYTES, LINE_BYTES);

  b[0] = 0x0a;
  put_frame(0xBD, b, 1);
  b[0] = feed & 0xff;
  b[1] = (feed >> 8) & 0xff;
  put_frame(0xA1, b, 2);
  {
    static const unsigned char a6b[11] = { 0xaa, 0x55, 0x17, 0, 0, 0, 0, 0, 0, 0, 0x17 };
    put_frame(0xA6, a6b, sizeof(a6b));
  }
  b[0] = 0x00;
  put_frame(0xA3, b, 1);
  put_frame(0xA3, b, 1);
  fflush(stdout);
}

int main(int argc, char *argv[])
{
  int fd, copies, density = 2, feed = 48, fs = 1, trim = 1, page = 0, nopt;
  cups_option_t *opts = NULL;
  cups_raster_t *ras;
  cups_page_header2_t h;
  const char *v;

  if (argc < 6 || argc > 7)
  {
    fprintf(stderr, "ERROR: %s job-id user title copies options [file]\n", argv[0]);
    return 1;
  }

  copies = atoi(argv[4]);
  if (copies < 1)
    copies = 1;

  nopt = cupsParseOptions(argv[5], 0, &opts);

  if ((v = cupsGetOption("Density", nopt, opts)) != NULL)
  {
    if (!strcasecmp(v, "Light") || !strcmp(v, "1"))
      density = 1;
    else if (!strcasecmp(v, "Dark") || !strcmp(v, "3"))
      density = 3;
    else
      density = 2;
  }
  if ((v = cupsGetOption("Dither", nopt, opts)) != NULL)
    fs = strcasecmp(v, "Threshold") != 0;
  trim = truthy(cupsGetOption("TrimBlank", nopt, opts), 1);
  if ((v = cupsGetOption("Feed", nopt, opts)) != NULL)
  {
    feed = atoi(v);
    if (feed < 0)
      feed = 0;
    if (feed > 1000)
      feed = 1000;
  }

  if (argc == 7)
  {
    fd = open(argv[6], O_RDONLY);
    if (fd < 0)
    {
      perror("ERROR: Cannot open input file");
      return 1;
    }
  }
  else
    fd = 0;

  if ((ras = cupsRasterOpen(fd, CUPS_RASTER_READ)) == NULL)
  {
    fputs("ERROR: Cannot open raster stream\n", stderr);
    return 1;
  }

  while (cupsRasterReadHeader2(ras, &h))
  {
    unsigned y, x, last;
    unsigned char *row, *lines;
    int *err_cur, *err_next;

    if (h.cupsBitsPerColor != 8 && h.cupsBitsPerColor != 1)
    {
      fprintf(stderr, "ERROR: Unsupported bit depth %u\n", h.cupsBitsPerColor);
      return 1;
    }
    if (h.cupsWidth > WIDTH)
      fprintf(stderr, "WARNING: Width %u > %d, cropping\n", h.cupsWidth, WIDTH);

    page++;
    fprintf(stderr, "PAGE: %d %d\n", page, copies);

    row = malloc(h.cupsBytesPerLine);
    lines = calloc(h.cupsHeight ? h.cupsHeight : 1, LINE_BYTES);
    err_cur = calloc(WIDTH + 2, sizeof(int));
    err_next = calloc(WIDTH + 2, sizeof(int));
    if (!row || !lines || !err_cur || !err_next)
    {
      fputs("ERROR: Out of memory\n", stderr);
      return 1;
    }

    for (y = 0; y < h.cupsHeight; y++)
    {
      int *t;

      if (cupsRasterReadPixels(ras, row, h.cupsBytesPerLine) < 1)
      {
        fputs("ERROR: Error reading raster\n", stderr);
        return 1;
      }

      for (x = 0; x < WIDTH; x++)
      {
        int g = (x < h.cupsWidth) ? pixel_gray(&h, row, x) : 255;
        int v2, nv;

        if (fs)
        {
          v2 = g + err_cur[x + 1] / 16;
          if (v2 < 0)
            v2 = 0;
          if (v2 > 255)
            v2 = 255;
          nv = (v2 >= 128) ? 255 : 0;
          {
            int e = v2 - nv;
            err_cur[x + 2] += e * 7;
            err_next[x] += e * 3;
            err_next[x + 1] += e * 5;
            err_next[x + 2] += e * 1;
          }
        }
        else
          nv = (g >= 128) ? 255 : 0;

        if (nv == 0)
          lines[(size_t)y * LINE_BYTES + (x >> 3)] |= (unsigned char)(1 << (x & 7));
      }

      t = err_cur;
      err_cur = err_next;
      err_next = t;
      memset(err_next, 0, (WIDTH + 2) * sizeof(int));
    }

    last = h.cupsHeight;
    if (trim)
    {
      while (last > 0)
      {
        unsigned char acc = 0;
        unsigned i;
        for (i = 0; i < LINE_BYTES; i++)
          acc |= lines[(size_t)(last - 1) * LINE_BYTES + i];
        if (acc)
          break;
        last--;
      }
      if (last == 0)
        last = h.cupsHeight < 8 ? h.cupsHeight : 8;   /* blank page */
    }

    if (last > 0)
    {
      int c;
      for (c = 0; c < copies; c++)
        emit_job(lines, last, density, feed);
    }

    free(row);
    free(lines);
    free(err_cur);
    free(err_next);
  }

  cupsRasterClose(ras);
  if (fd)
    close(fd);

  if (page == 0)
  {
    fputs("ERROR: No pages to print\n", stderr);
    return 1;
  }
  return 0;
}
