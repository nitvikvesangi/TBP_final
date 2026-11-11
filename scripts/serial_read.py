import os, fcntl, struct, select, sys, time
P='/dev/cu.usbserial-0001'; BAUD=115200; IOSSIOSPEED=0x80045402
fd=os.open(P, os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
fcntl.ioctl(fd, IOSSIOSPEED, struct.pack('I', BAUD))
end=time.time()+float(sys.argv[1] if len(sys.argv)>1 else 8)
out=b''
while time.time()<end:
    r,_,_=select.select([fd],[],[],0.3)
    if r:
        try: d=os.read(fd,4096)
        except BlockingIOError: continue
        if d: out+=d
os.close(fd)
sys.stdout.write(out.decode('utf-8','replace'))
