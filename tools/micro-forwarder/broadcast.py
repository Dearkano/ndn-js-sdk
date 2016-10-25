#!/usr/bin/env python

import sys
import struct
import socket
import select
import time
import threading

class SocketPoller(object):
    """
    Create a new SocketPoller and register with the given sock

    :param socket sock: The socket to register with.
    """
    def __init__(self, sock):
        self._socket = sock
        self._poll = None
        self._kqueue = None
        self._kevents = None

        if hasattr(select, "poll"):
            # Set up _poll.  (Ubuntu, etc.)
#pylint: disable=E1103
            self._poll = select.poll()
            self._poll.register(sock.fileno(), select.POLLIN)
#pylint: enable=E1103
        elif hasattr(select, "kqueue"):
            ## Set up _kqueue. (BSD and OS X)
            self._kqueue = select.kqueue()
            self._kevents = [select.kevent(
              sock.fileno(), filter = select.KQ_FILTER_READ,
              flags = select.KQ_EV_ADD | select.KQ_EV_ENABLE |
                      select.KQ_EV_CLEAR)]
        elif not hasattr(select, "select"):
            # Most Python implementations have this fallback, so we
            #   don't expect this error.
            raise RuntimeError("Cannot find a polling utility for sockets")

    def isReady(self):
        """
        Check if the socket given to the constructor has data to receive.

        :return: True if there is data ready to receive, otherwise False.
        :rtype: bool
        """
        if self._poll != None:
            isReady = False
            # Set timeout to 0 for an immediate check.
            for (fd, pollResult) in self._poll.poll(0):
#pylint: disable=E1103
                if pollResult > 0 and pollResult & select.POLLIN != 0:
                    return True
#pylint: enable=E1103

            # There is no data waiting.
            return False
        elif self._kqueue != None:
            # Set timeout to 0 for an immediate check.
            return len(self._kqueue.control(self._kevents, 1, 0)) != 0
        else:
            # Use the select fallback which is less efficient.
            # Set timeout to 0 for an immediate check.
            isReady, _, _ = select.select([self._socket], [], [], 0)
            return len(isReady) != 0

NDN_MULTICAST_IP = '224.0.23.170'
NDN_MULTICAST_PORT = 56363

# See the multicast tutorial at https://pymotw.com/2/socket/multicast.html .
inSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
inSocket.bind(('', NDN_MULTICAST_PORT))
inSocketPoller = SocketPoller(inSocket)
# Tell the operating system to add the socket to the multicast group on all
# interfaces.
group = socket.inet_aton(NDN_MULTICAST_IP)
mreq = struct.pack('4sL', group, socket.INADDR_ANY)
inSocket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

outSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
outSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# Don't send packets in a loop.
outSocket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
# Set a timeout so the socket does not block indefinitely when trying to receive
# data.
outSocket.settimeout(0.2)
# Set the time-to-live for messages to 1 so they do not go past the local
# network segment.
outSocket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

buffer = bytearray(10000)

def printOneBroadcasted():
    while True:
        if not inSocketPoller.isReady():
            # There is no data waiting.
            break

        nBytesRead, _ = inSocket.recvfrom_into(buffer)
        if nBytesRead <= 0:
            # Since we checked for data ready, we don't expect this.
            break

        sys.stdout.write(buffer[0:nBytesRead])
        sys.stdout.flush()

printAllBroadcastedEnabled = True
def printAllBroadcasted():
    while printAllBroadcastedEnabled:
        printOneBroadcasted()
        # We need to sleep for a few milliseconds so we don't use 100% of the CPU.
        time.sleep(0.1)

    inSocket.close()

def multicastAllStdin():
    # Loop until there is no more data in stdin.
    while True:
        # The Native Messaging packet starts with a 4-byte length
        rawLength = sys.stdin.read(4)
        if len(rawLength) == 0:
            # Input EOF. Finished.
            return

        messageLength = struct.unpack('@I', rawLength)[0]
        message = sys.stdin.read(messageLength)

        outSocket.sendto(rawLength + message, (NDN_MULTICAST_IP, NDN_MULTICAST_PORT))

thread = threading.Thread(target=printAllBroadcasted)
thread.start()
multicastAllStdin()
printAllBroadcastedEnabled = False

outSocket.close()
