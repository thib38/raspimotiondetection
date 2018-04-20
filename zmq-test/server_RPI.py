#
#   Hello World server in Python
#   Binds REP socket to tcp://*:5555
#   Expects b"Hello" from client, replies with b"World"
#

import time
import zmq
import pickle

context = zmq.Context()
socket = context.socket(zmq.REP)
socket.bind("tcp://*:5555")
print("server binded on port 5555")

while True:
    #  Wait for next request from client
    serialized = socket.recv()
    image_in_numpy_bgr_format= pickle.loads(serialized)
    print("Received request")
    # print(type(image_in_numpy_bgr_format))
    print(image_in_numpy_bgr_format.shape)
    # print(image_in_numpy_bgr_format)

    #  Do some 'work'
    # time.sleep(1)

    #  Send reply back to client with same data
    socket.send(b"OK")