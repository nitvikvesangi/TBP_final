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
drain(2)
os.write(fd, b"reboot\n")
sys.stdout.write("--- after reboot ---\n")
sys.stdout.write(drain(7).decode('utf-8','replace'))
os.write(fd, b"list\n")
sys.stdout.write("--- list ---\n")
sys.stdout.write(drain(3).decode('utf-8','replace'))
sys.stdout.flush()
