import sys
from time import sleep
from  picamera import PiCamera
import cv2
import imutils
print(sys.version_info)


CAMERA_WARMUP_TIME = 2.5  # seconds
RESOLUTION = [640,400]
FPS = 16
MIN_AREA = 5000


camera = PiCamera()



camera.start_preview()
for _ in range(10):
    sleep(5)
    camera.capture('/home/pi/Pictures/image' + str(_) + '.jpg')
    print("picture number: ", str(_))

camera.stop_preview()









