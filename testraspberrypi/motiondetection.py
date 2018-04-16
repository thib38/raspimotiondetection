import sys
import traceback
import os
from time import sleep
import  cv2
from  picamera.array import PiRGBArray
from  picamera import PiCamera
import imutils
import logging
import numpy as np
import datetime
print(sys.version_info)
# set-up logger before anything - two  handlers : one on console, the other one on file
formatter = \
    logging.Formatter("%(asctime)s :: %(funcName)s :: %(levelname)s :: %(message)s")

# handler_file = logging.FileHandler("photo1.log", mode="a", encoding="utf-8")
handler_console = logging.StreamHandler()

# handler_file.setFormatter(formatter)
handler_console.setFormatter(formatter)

# handler_file.setLevel(logging.DEBUG)
handler_console.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # A D A P T   LOGGING LEVEL        H E R E
# logger.addHandler(handler_file)
logger.addHandler(handler_console)
def handle_uncaugth_exception(*exc_info):
    """
    This function will be subsituted to sys.except_hook standard function that is raised when ecxeptions are raised and
    not caugth by some try: except: block
    :param exc_info: (exc_type, exc_value, exc_traceback)
    :return: stop program with return code 1
    """
    stack = traceback.extract_stack()[:-3] + traceback.extract_tb(exc_info[1].__traceback__)  # add limit=??
    pretty = traceback.format_list(stack)
    text = ''.join(pretty) + '\n  {} {}'.format(exc_info[1].__class__, exc_info[1])
    # text = "".join(traceback.format_exception(*exc_info))
    logger.error("Unhandled exception: %s", text)
    sys.exit(1)
sys.excepthook = handle_uncaugth_exception  # reassign so that log is fed with problem

def handle_frame(image_in_numpy_bgr_format, time_stamp_string):

    cwd = os.getcwd()
    print(cwd)
    print(time_stamp_string)
    cv2.imwrite(cwd + "/" + time_stamp_string + ".jpg", image_in_numpy_bgr_format)

CAMERA_WARMUP_TIME = 2.5  # seconds
RESOLUTION = (640,480)
FPS = 16
MIN_AREA = 5000
DELTA_THRESHOLD = 5


# camera = PiCamera()
with PiCamera() as camera:
    camera.resolution = RESOLUTION
    camera.framerate = FPS
    rawCapture = PiRGBArray(camera, size=RESOLUTION)

    # allow the camera to warmup, then initialize the average frame, last
    # uploaded timestamp, and frame motion counter
    print("[INFO] warming up...")
    sleep(CAMERA_WARMUP_TIME)
    avg = None
    lastUploaded = datetime.datetime.now()
    motionCounter = 0

    # capture frames from the camera
    for f in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
        print("beg of loop")
        # grab the raw NumPy array representing the image and initialize
        # the timestamp and occupied/unoccupied text
        frame = f.array
        timestamp = datetime.datetime.now()
        text = "Unoccupied"

        # resize the frame, convert it to grayscale, and blur it
        frame = imutils.resize(frame, width=500)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        # if the average frame is None, initialize it
        if avg is None:
            print("[INFO] starting background model...")
            avg = gray.copy().astype("float")
            rawCapture.truncate(0)  # clear buffer before next iteration
            continue

        # accumulate the weighted average between the current frame and
        # previous frames, then compute the difference between the current
        # frame and running average
        cv2.accumulateWeighted(gray, avg, 0.5)
        frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(avg))

        # threshold the delta image, dilate the thresholded image to fill
        # in holes, then find contours on thresholded image
        thresh = cv2.threshold(frameDelta, DELTA_THRESHOLD, 255,
                               cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
        cnts = cnts[0] if imutils.is_cv2() else cnts[1]

        # loop over the contours
        for c in cnts:
            # if the contour is too small, ignore it
            if cv2.contourArea(c) < MIN_AREA:
                continue

            # compute the bounding box for the contour, draw it on the frame,
            # and update the text
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            text = "Occupied"
            print("=======MOTION DETECTED============")

            # draw the text and timestamp on the frame
            ts = timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
            cv2.putText(frame, "Room Status: {}".format(text), (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            cv2.putText(frame, ts, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                        0.35, (0, 0, 255), 1)

            print(ts)
            handle_frame(frame, ts.replace(" ","_").replace(":","_"))

        rawCapture.truncate(0)  # clear buffer before next iteration