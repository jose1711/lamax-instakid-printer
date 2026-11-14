CUPS_SERVERBIN ?= $(shell cups-config --serverbin)
CUPS_DATADIR   ?= $(shell cups-config --datadir)
PRINTER        ?= InstaKid2
URI            ?= instakid://BQ95B
MEDIA          ?= 48x50mm

all: cups/rastertoinstakid

cups/rastertoinstakid: cups/rastertoinstakid.c
	$(CC) $(CFLAGS) -O2 -Wall -o $@ $< $(LDFLAGS) $(shell cups-config --libs)

install: all
	install -D -m 755 cups/rastertoinstakid $(DESTDIR)$(CUPS_SERVERBIN)/filter/rastertoinstakid
	install -D -m 700 cups/instakid $(DESTDIR)$(CUPS_SERVERBIN)/backend/instakid
	install -D -m 644 cups/instakid2.ppd $(DESTDIR)$(CUPS_DATADIR)/model/instakid2.ppd

# create the print queue (run after `make install`, needs root)
add-printer:
	lpadmin -p $(PRINTER) -E -v $(URI) -P $(CUPS_DATADIR)/model/instakid2.ppd \
	        -o media=$(MEDIA) -o printer-is-shared=false

remove-printer:
	lpadmin -x $(PRINTER)

uninstall:
	rm -f $(DESTDIR)$(CUPS_SERVERBIN)/filter/rastertoinstakid \
	      $(DESTDIR)$(CUPS_SERVERBIN)/backend/instakid \
	      $(DESTDIR)$(CUPS_DATADIR)/model/instakid2.ppd

# offline checks (no printer needed)
check: all
	cupstestppd -I filters -W translations -W sizes cups/instakid2.ppd
	python3 -c "import ast;[ast.parse(open(f).read()) for f in ('cups/instakid','cups/verify_job.py','instakid_print.py','tools/nrf_follow.py')]; print('python syntax ok')"

clean:
	rm -f cups/rastertoinstakid

.PHONY: all install add-printer remove-printer uninstall check clean
