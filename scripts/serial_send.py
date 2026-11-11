import os, fcntl, struct, select, sys, time
P='/dev/cu.usbserial-0001'; IOSSIOSPEED=0x80045402
fd=os.open(P, os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
fcntl.ioctl(fd, IOSSIOSPEED, struct.pack('I', 115200))
def drain(t):
    out=b''; end=time.time()+t
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.2)
        if r:
            try: d=os.read(fd,4096)
            except BlockingIOError: continue
            if d: out+=d
    return out
sys.stdout.write(drain(3).decode('utf-8','replace'))
for c in sys.argv[1:]:
    os.write(fd, (c+"\n").encode()); time.sleep(0.4)
    sys.stdout.write(drain(1.5).decode('utf-8','replace'))
sys.stdout.flush()
