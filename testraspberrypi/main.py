from  picamera import PiCamera
from time import sleep
import sys
print(sys.version_info)

camera = PiCamera()
camera.start_preview()
for _ in range(10):
    sleep(5)
    camera.capture('/home/pi/Pictures/image' + str(_) + '.jpg')
    print("picture number: ", str(_))

camera.stop_preview()

# gfdhqk ghqddkg hk








