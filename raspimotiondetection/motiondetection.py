import sys
import traceback
import os
import psutil
import datetime
from time import sleep
import  cv2
from  picamera.array import PiRGBArray
from  picamera import PiCamera
import imutils
import logging
import numpy as np
import datetime
import zmq
import pickle
import ipaddress
import socket
import threading

from pathlib import Path
print(sys.version_info)

class SendFrameToCentral:

    def __init__(self, camera_id, host="192.168.1.36", port="5555"):
        # Valid IPV4 address
        try:
            ipaddress.ip_address(host)
        except ValueError:
            logger.error("%s is not valid IP address", host)
            raise Exception
        # valid TCP port value
        if type(port) != str:
            logger.error("%s is not a character string", str(port))
            raise Exception
        elif (int(port) > 49152) or (int(port) < 1000):
            logger.error("%s port value must be in 1000 to 49152 range", str(port))
            raise Exception

        self.camera_id = camera_id
        self.request_time_out = 2500
        self.request_retries = 3
        self.server_endpoint = "tcp://" + host + ":"  + port

        self.context = zmq.Context()

        self.client = self.context.socket(zmq.REQ)
        self.client.connect(self.server_endpoint)

        self.poll = zmq.Poller()
        self.poll.register(self.client, zmq.POLLIN)

        self.connection_dropped = False

        return

    def send_multipart_message(self, message):
        """

        :param message: List containing already serialized objects as zmq accepts only bytes
        :return: True if succesful False otherwise
        """

        # reopen connection if last call left it dropped
        if self.connection_dropped:
            self.client = self.context.socket(zmq.REQ)
            self.client.connect(self.server_endpoint)
            self.poll.register(self.client, zmq.POLLIN)
            self.connection_dropped = False

        rc = True
        sequence = 0
        retries_left = self.request_retries
        while retries_left:
            sequence += 1
            self.client.send_multipart(message)

            expect_reply = True
            while expect_reply:
                socks = dict(self.poll.poll(self.request_time_out))
                if socks.get(self.client) == zmq.POLLIN:
                    reply = self.client.recv()
                    if not reply:
                        break
                    if reply.decode('utf-8') == "ack":
                        retries_left = 0
                        expect_reply = False
                    else:
                        logger.warning("malformed response %s from server", str(reply))
                        # shouldn't we abandon ?
                else:
                    logger.warning("no response from server, retrying...")
                    # socket migth be confused - close and remove
                    self.client.setsockopt(zmq.LINGER, 0)
                    self.client.close()
                    self.poll.unregister(self.client)
                    retries_left -= 1
                    if retries_left == 0:
                        logger.error("Server seems to be offline, abandoning")
                        self.connection_dropped = True
                        rc = False
                        break
                    logger.warning("Reconnecting and resending")
                    #create new connection
                    self.client = self.context.socket(zmq.REQ)
                    self.client.connect(self.server_endpoint)
                    self.poll.register(self.client, zmq.POLLIN)
                    self.client.send_multipart(message)

        return rc

    def send_numpy_bgr(self,image_numpy_bgr):
        """
        send serialized with pickle image to server
        embedded retries mechanism in case of network issue

        :param image_numpy_bgr: variable name is self explanatory
        :return: True if sending OK False otherwise
        """

        serialized = pickle.dumps(image_numpy_bgr)
        message = [bytes(self.camera_id), serialized]
        # TODO replace pickle with JSON as pickle is unsafe and can inject malicious code

        return self.send_multipart_message(message)


class SendFrameToLocalDisk:
    """
    Stores picture on local disk until max_disk_utilization_threshold is reached under path

    folders are organozed as follows:
      camera_id ---> DDMMYYYY --> timestamp.jpg
               |---> DDMMYYYY --> timestamp.jpg

    """
    def __init__(self, camera_id, path, max_disk_utilization_threshold=0.8):

        self.camera_id = camera_id
        self.top_folder_path = Path(os.path.join(path, str(camera_id)))
        self.max_disk_utilization_threshold = max_disk_utilization_threshold


        # create camera_id folder if it does not exists
        if not self.top_folder_path.exists():
            os.mkdir(str(self.top_folder_path))

        if psutil.disk_usage("/").percent > 80:
            logger.error("file system almost full: %s used" % str(psutil.disk_usage("/").percent))


    def send_numpy_bgr(self, image_in_numpy_bgr_format, time_stamp_string):

        # check if today's directory is already created
        today_YYYYMMDD = datetime.datetime.today().strftime('%Y%m%d')
        path_of_the_day_string = os.path.join(str(self.top_folder_path), today_YYYYMMDD)
        if not Path(path_of_the_day_string).exists():
            os.mkdir(path_of_the_day_string)

        disk_usage_percentage = psutil.disk_usage("/").percent
        if disk_usage_percentage <= 80:  #
            cv2.imwrite(path_of_the_day_string + "/" + time_stamp_string + ".jpg", image_in_numpy_bgr_format)
        elif 80 < disk_usage_percentage < 89:  #
            logger.error("file system almost full: %s used" % str(psutil.disk_usage("/").percent))
            cv2.imwrite(path_of_the_day_string + "/" + time_stamp_string + ".jpg", image_in_numpy_bgr_format)
        elif 89 < disk_usage_percentage < 95:  #
            logger.critical("file system almost full: %s used" % str(psutil.disk_usage("/").percent))
            cv2.imwrite(path_of_the_day_string + "/" + time_stamp_string + ".jpg", image_in_numpy_bgr_format)
        elif disk_usage_percentage >= 95:
            logger.critical("file system full: %s used - STOPPING APPLICATION" % str(psutil.disk_usage("/").percent))
            sys.exit(-1)


class GetFrameFromCamera:

    def __init__(self,
                 resolution,
                 fps,
                 motion_detection_min_area,
                 motion_detection_delta_threshold,
                 camera_id
                 ):

        # initiate camera
        self.camera_id = camera_id
        self.camera = PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = fps
        self.rawCapture = PiRGBArray(self.camera, size=resolution)

        # allow the camera to warmup, then initialize the average frame, last
        print("[INFO] warming up...")
        sleep(CAMERA_WARMUP_TIME)

        # set motion detection sensitiveness
        self.motion_detection_min_area = motion_detection_min_area
        self.motion_detection_delta_threshold = motion_detection_delta_threshold

        # set sending mode to "local" or "send_to_video_server"
        # in "local" sending mode the capture mode is  forced to "motion-detected" so as to save space on local
        # raspberry SD card storage
        self.sending_mode = "local"
        # set capture mode "all" or "motion-detection"
        self.capture_mode = 'motion-detection'   # send all picture by default

    def loop_forever_get_frame(self):

        # uploaded timestamp, and frame motion counter
        avg = None
        lastUploaded = datetime.datetime.now()
        motionCounter = 0

        # capture frames from the camera
        for f in self.camera.capture_continuous(self.rawCapture, format="bgr", use_video_port=True):
            # print("frame captured")
            # grab the raw NumPy array representing the image and initialize
            # the timestamp
            frame = f.array
            timestamp = datetime.datetime.now()

            if self.capture_mode == "motion-detection":

                # resize the frame, convert it to grayscale, and blur it
                frame = imutils.resize(frame, width=500)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                # if the average frame is None, initialize it
                if avg is None:
                    print("[INFO] starting background model...")
                    avg = gray.copy().astype("float")
                    self.rawCapture.truncate(0)  # clear buffer before next iteration
                    continue

                # accumulate the weighted average between the current frame and
                # previous frames, then compute the difference between the current
                # frame and running average
                cv2.accumulateWeighted(gray, avg, 0.5)
                frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(avg))

                # threshold the delta image, dilate the thresholded image to fill
                # in holes, then find contours on thresholded image
                thresh = cv2.threshold(frameDelta, self.motion_detection_delta_threshold, 255,
                                       cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)
                cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
                cnts = cnts[0] if imutils.is_cv2() else cnts[1]

                # loop over the contours
                for c in cnts:
                    # if the contour is too small, ignore it
                    if cv2.contourArea(c) < self.motion_detection_min_area:
                        continue

                    # compute the bounding box for the contour, draw it on the frame,
                    # and update the text
                    # (x, y, w, h) = cv2.boundingRect(c)
                    # cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    # text = "Occupied"
                    print("=======MOTION DETECTED============")

                    # draw the text and timestamp on the frame
                    ts = timestamp.strftime("%A %d %B %Y %I:%M:%S:%f%p")
                    # cv2.putText(frame, "Room Status: {}".format(text), (10, 20),
                    #             cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    cv2.putText(frame, ts, (10, 20), cv2.FONT_HERSHEY_SIMPLEX,
                                0.35, (0, 0, 255), 1)

                    print("sent motion detection")
                    handle_frame(frame, ts.replace(" ", "_").replace(":", "_"))

            elif self.capture_mode == "all":
                ts = timestamp.strftime("%A %d %B %Y %I:%M:%S%f%p")
                print("sent all")
                handle_frame(frame, ts.replace(" ", "_").replace(":", "_"))

            else:  # sends nothing
                pass


            self.rawCapture.truncate(0)  # clear buffer before next iteration


def listen_video_server_queries(host_ip_address, tcp_port):
    """
    This function is to be started in a separate thread
    It is starting a zmq server and accept queries from the video server

    """

    # get ip address of the host running the program
    # host_ip_address = socket.gethostbyname(socket.gethostname())  # TODO DOESN'T WORK ON LINUX RETURNS 127.0.0.1
    # start zmq listener
    zmq_context = zmq.Context()
    zmq_socket_listener = zmq_context.socket(zmq.REP)
    zmq_socket_listener.bind("tcp://" + host_ip_address + ":" + tcp_port)
    print("zmq server started...")

    while True:
        # get request
        response = "ok"
        message = zmq_socket_listener.recv_json()
        print("query received : %s" % str(message))
        # whenever a message from video server is received sending_mode is switched to "send_to_video_server"
        camera_handler.sending_mode = "send_to_video_server"

        # deal with message
        if message == "test":
            pass
        elif message == "capture_mode_set_to_motion_detection":
            camera_handler.capture_mode = "motion-detection"
        elif message == "capture_mode_set_to_all_frames":
            camera_handler.capture_mode = "all"


        # respond to request
        zmq_socket_listener.send_json(response)


def handle_frame(image_in_numpy_bgr_format, time_stamp_string):

    if camera_handler.sending_mode == "send_to_video_server":

        if not send_over_lan.send_numpy_bgr(image_in_numpy_bgr_format):
            logger.warning("LAN connection not working / switching to local storage")
            camera_handler.sending_mode = "local"
            send_to_local_disk.send_numpy_bgr(image_in_numpy_bgr_format, time_stamp_string)

    elif camera_handler.sending_mode == "local":
        send_to_local_disk.send_numpy_bgr(image_in_numpy_bgr_format, time_stamp_string)

    else:
        logger.critical("camera_handler.sending_mode: %s not implemnted" % camera_handler.sending_mode)
        raise NotImplementedError


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


if __name__ == "__main__":

    CAMERA_WARMUP_TIME = 2.5  # seconds
    RESOLUTION = (640,480)
    FPS = 16
    MIN_AREA = 5000
    DELTA_THRESHOLD = 5
    CAMERA_ID = 1
    HOST_IP_ADDRESS = "192.168.1.27"
    LISTENING_TCP_PORT = "5556"

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

    # catch unhandled exceptions
    sys.excepthook = handle_uncaugth_exception  # reassign so that log is fed with problem

    # start zmq server dealing with queries from video server in a separate thread
    wait_from_video_server_queries = threading.Thread(target=listen_video_server_queries,
                                                      args=(HOST_IP_ADDRESS, LISTENING_TCP_PORT),)
    wait_from_video_server_queries.start()

    # initiate zmq context to send picture to server
    send_over_lan = SendFrameToCentral(CAMERA_ID)

    # initiate write to local disk context in current working directory
    send_to_local_disk = SendFrameToLocalDisk(CAMERA_ID, os.getcwd())

    # set camera parameters
    camera_handler = GetFrameFromCamera(RESOLUTION,
                                        FPS,
                                        MIN_AREA,
                                        DELTA_THRESHOLD,
                                        CAMERA_ID)

    # start frame acquisition loop
    camera_handler.loop_forever_get_frame()
