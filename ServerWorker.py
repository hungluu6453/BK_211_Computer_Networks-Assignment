from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	DESCRIBE = 'DESCRIBE'
	CHANGEFRAME = 'CHANGEFRAME'
	CHANGESPEED = 'CHANGESPEED'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2

	Played = 0
	TPF = 0.05
	SPD = 0.05
	clientInfo = {}
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self): #sever always wait for request
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0]  # a socket object to send and receive data
		while True:            
			data = connSocket.recv(256)  # data is a python bytes object -> the request, not the video
			if data:
				print("Data received:\n" + data.decode("utf-8"))  # decode from hexadecimal to string
				self.processRtspRequest(data.decode("utf-8"))
	
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		request = data.split('\n')  # the whole request (multiple lines)
		line1 = request[0].split(' ')  # the first line Ex: SETUP movie.Mjpeg RTSP/1.0
		requestType = line1[0] # get SETUP
		
		# Get the media file name
		self.filename = line1[1] # get movie.Mjpeg
		
		# Get the RTSP sequence number 
		seq = request[1].split(' ')  # Ex: CSeq: 1
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				# Update state
				print("processing SETUP\n")
				
				try:
					self.clientInfo['videoStream'] = VideoStream(self.filename)
					self.totalFrame = int(self.clientInfo['videoStream'].totalFrameNum)
					self.state = self.READY
					self.SPD = self.TPF
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1], requestType)
				
				# Get the RTP/UDP port from the last line
				self.clientInfo['rtpPort'] = request[2].split(' ')[3]

		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.Played = 1
				self.state = self.PLAYING
				
				# Create a new socket for RTP/UDP
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				
				self.replyRtsp(self.OK_200, seq[1])
				
				# Create a new thread and start sending RTP packets
				self.clientInfo['event'] = threading.Event()
				self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				self.clientInfo['event'].set()
			
				self.replyRtsp(self.OK_200, seq[1])

				#Additional
				#self.clientInfo["rtpSocket"].shutdown(socket.SHUT_RDWR)
						
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			if self.Played != 0:
				self.clientInfo['event'].set()
				self.clientInfo['rtpSocket'].close()
			
			self.replyRtsp(self.OK_200, seq[1])
			
			self.state = self.INIT
			self.Played = 0
		
		# Process DESCRIBE request
		elif requestType == self.DESCRIBE:
			print("processing DESCRIBE\n")
			self.replyDescibe(self.OK_200,seq[1])	

		elif requestType == self.CHANGEFRAME:
			print("processing CHANGEFRAME")
			self.changeFrameNbr (request[3].split(' ')[1])

		elif requestType == self.CHANGESPEED:
			print("processing CHANGESPEED\n")
			self.SPD = self.TPF * (2 - float(request[3].split(' ')[1]))

	def changeFrameNbr (self, frameNum):
		print ("Change to Frame " + str(frameNum) + '\n')
		self.clientInfo['videoStream'].setFrame(frameNum)
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			self.clientInfo['event'].wait(self.SPD) #0.05
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet():
				self.clientInfo["rtpSocket"].close()
				break 
			
			data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpPort'])
					#print (str(address) +' + '+str(port))
					self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber),(address,port))
					print("Sent frame")
					if frameNumber == self.totalFrame:
						print ("End of movie.")
						self.clientInfo['videoStream'] = VideoStream(self.filename)
						#self.clientInfo["rtpSocket"].close()
						break 
				except:
					print("Connection Error")
					#print('-'*60)
					#traceback.print_exc(file=sys.stdout)
					#print('-'*60)
			

	def makeRtp(self, payload, frameNbr):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 0
		pt = 26 # MJPEG type
		seqnum = frameNbr
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq, requestType = ''):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			if requestType == self.SETUP:
				reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session']) \
				+ '\nTotalFrameofVideo: ' + str(self.totalFrame) \
				+ '\nTimeperFrame: ' + str(self.TPF)
			else:
				reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
			print("Reply sent")
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")

	def describe(self):
		seq1 = "\nFPS: " + str(1/self.TPF) + ", v = 0\nm = video " + str(self.clientInfo['rtpPort']) + " RTP/AVP 26\na=control:streamid=" \
			 + str(self.clientInfo['session']) + "\na=mimetype:string;\"video/Mjpeg\"\n-----"
		seq2 = "\nEncoding: UTF-8" + "\nDescribe-Base: " + str(self.clientInfo['videoStream'].filename) + "\nDescribe-Length: " \
			 + str(len(seq1)) + "\n"
		return seq1 + seq2

	def replyDescibe(self,code,seq):
		des = self.describe()
		if code == self.OK_200:
			reply = "RTSP/1.0 200 OK\nCSeq: " + seq + "\nSession: " + str(self.clientInfo['session']) + "\n" + des
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")