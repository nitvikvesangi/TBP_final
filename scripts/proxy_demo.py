import os, fcntl, struct, select, sys, time
P='/dev/cu.usbserial-0001'; IOSSIOSPEED=0x80045402
fd=os.open(P, os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
fcntl.ioctl(fd, IOSSIOSPEED, struct.pack('I', 115200))
def drain(t):
    out=b''; end=time.time()+t
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.15)
        if r:
            try: d=os.read(fd,4096)
            except BlockingIOError: continue
            if d: out+=d
    return out
def send(c, wait=0.8):
    os.write(fd,(c+"\n").encode()); return drain(wait).decode('utf-8','replace')
sys.stdout.write(drain(2).decode('utf-8','replace'))
sys.stdout.write("--- list before ---\n"+send("list",1.5))
for uid in ("sim 11 22 33 44","sim 55 66 77 88","sim AA BB CC DD"):
    sys.stdout.write(send(uid,0.7))
sys.stdout.write("--- list after ---\n"+send("list",1.5))
sys.stdout.write("--- queue ---\n"+send("queue",1.0))
