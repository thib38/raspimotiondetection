#
#   Hello World client in Python
#   Connects REQ socket to tcp://localhost:5555
#   Sends "Hello" to server, expects "World" back
#

import zmq
import numpy as np
import pickle

verb = b"verb"
test_frame = np.zeros(shape=(640,480,3))
serialized = pickle.dumps(test_frame,)
multipart_message = [verb,serialized]
context = zmq.Context()

#  Socket to talk to server
print("Connecting to hello world server…")
socket = context.socket(zmq.REQ)
socket.connect("tcp://localhost:5555")

#  Do 10 requests, waiting each time for a response
for request in range(1000000):
    print("Sending request %s …" % request)
    # socket.send(b"Hello")
    socket.send_multipart(multipart_message)

    #  Get the reply.
    message = socket.recv()
    # print("Received reply %s [ %s ]" % (request, message))
    # test_frame_received = pickle.loads(message)
    print("Received reply %s " % message)
    # print(type(test_frame_received))
    # print(test_frame_received.shape)
    # print(test_frame_received)