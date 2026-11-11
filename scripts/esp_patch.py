import struct, fcntl
import serial.serialposix as spp
IOSSIOSPEED = 0x80045402
def _reconfigure_port(self, force_update=False):
    # AppleUSBSLCOM rejects tcsetattr; the line is already raw, so only baud matters.
    fcntl.ioctl(self.fd, IOSSIOSPEED, struct.pack('I', int(self._baudrate)))
spp.Serial._reconfigure_port = _reconfigure_port
