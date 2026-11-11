import os, fcntl, struct, select, sys, time
P='/dev/cu.usbserial-0001'; BAUD=115200; IOSSIOSPEED=0x80045402
fd=os.open(P, os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
fcntl.ioctl(fd, IOSSIOSPEED, struct.pack('I', BAUD))
sys.stdout.write(">>> listening on %s at %d baud (Ctrl+C to stop)\n" % (P, BAUD))
sys.stdout.flush()
while True:
    r,_,_=select.select([fd],[],[],0.5)
    if r:
        try: d=os.read(fd,4096)
        except BlockingIOError: continue
        if d:
            sys.stdout.write(d.decode('utf-8','replace'))
            sys.stdout.flush()
