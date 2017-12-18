#!/usr/bin/python

import socket  
import time
import fcntl
import re
import os
import errno
import struct
import select
import json
from threading import Thread
from time import sleep
from collections import OrderedDict

# Constants definitions
MCAST_GRP = '239.255.255.250'
WAIT_TIMEOUT = 2  # in seconds
CRON_TIMEOUT = 5  # in minutes
RESPONSE_TIMEOUT = 5 # in seconds

def sendSearchBroadcast(scanSocket):
  '''
  multicast search request to all hosts in LAN, do not wait for response
  '''
  multicastAddress = (MCAST_GRP, 1982)
  print("Sending search request...")
  msg = "M-SEARCH * HTTP/1.1\r\n" 
  msg = msg + "HOST: 239.255.255.250:1982\r\n"
  msg = msg + "MAN: \"ssdp:discover\"\r\n"
  msg = msg + "ST: wifi_bulb"

  scanSocket.sendto(msg, multicastAddress)

  print("Sending search request done.")

def getParamValue(data, param):
  '''
  match line of 'param = value'
  '''
  regex = re.compile(param+":\s*([ -~]*)") #match all printable characters
  match = regex.search(data)

  value = ""

  if match != None:
    value = match.group(1)

  return value

def processResponse(data):
  response = []

  if len(data):
    regex = re.compile("Location: yeelight://[^0-9]*([0-9]{1,3}(\.[0-9]{1,3}){3}):([0-9]*)")
    match = regex.search(data)

    if match == None:
      return response
    
    hostIP = match.group(1)
    hostPort = match.group(3)
    hostID = getParamValue(data, "id")
    hostPower = getParamValue(data, "power")

    if len(hostIP) == 0 or len(hostPort) == 0 or len(hostID) == 0 or len(hostPower) == 0:
      return response

    response = [hostIP, hostPort, hostID, hostPower]

  return response

def operateOnBulb(ip, port, method, params):
  '''
  Operate on bulb; no gurantee of success.
  Input data 'params' must be a compiled into one string.
  E.g. params="1"; params="\"smooth\"", params="1,\"smooth\",80"
  '''
  try:
    tcpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    print("connect ",ip, port ,"...")

    tcpSocket.connect((ip, int(port)))

    msg = "{\"id\":" + str(1) + ",\"method\":\""
    msg += method + "\",\"params\":[" + params + "]}\r\n"

    tcpSocket.send(msg)

    response = select.select([tcpSocket], [], [], RESPONSE_TIMEOUT)

    if response[0]:
      try:
        data = tcpSocket.recv(2048)
      except socket.error, e:
        error = e.args[0]
        print(error)      

    print(data)

    tcpSocket.close()
  except Exception as e:
    print "Unexpected error:", e

def getCronJob(ip, port):
  try:
    tcpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    tcpSocket.connect((ip, int(port)))

    msg = "{\"id\":1,\"method\":\"cron_get\",\"params\":[0]}\r\n"

    tcpSocket.send(msg)

    response = select.select([tcpSocket], [], [], RESPONSE_TIMEOUT)
    
    data = ""

    if response[0]:
      try:
        data = tcpSocket.recv(2048)
      except socket.error, e:
        error = e.args[0]
        print(error)
        return []

    tcpSocket.close()

    if len(data):
      jsonObject = json.loads(data)
      if "result" in jsonObject:
        if len(jsonObject["result"]):
          resultType = jsonObject["result"][0]["type"]
          resultDelay = jsonObject["result"][0]["delay"]
          return [resultType, resultDelay]

    return []
  except Exception as e:
    print "Unexpected error:", e
  
  return []

def setCronJob(ip, port, timeout):
  try:
    tcpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    tcpSocket.connect((ip, int(port)))

    msg = "{\"id\":1,\"method\":\"cron_add\",\"params\":[0, " + str(timeout) + "]}\r\n"

    tcpSocket.send(msg)

    response = select.select([tcpSocket], [], [], RESPONSE_TIMEOUT)
    
    data = ""

    if response[0]:
      try:
        data = tcpSocket.recv(2048)
        print(data)
      except socket.error, e:
        error = e.args[0]
        print(error)
        return []
  except Exception as e:
    print "Unexpected error:", e

  tcpSocket.close()

def executeSearch(scanSocket, listenSocket):
  detectedBulbs = {}

  sendSearchBroadcast(scanSocket)

  readGroup = select.select([scanSocket, listenSocket], [], [], RESPONSE_TIMEOUT)

  if readGroup[0]:
    try:
      data = scanSocket.recv(2048)
    except socket.error, e:
      error = e.args[0]
      print(error)

  responseList = processResponse(data)

  if len(responseList):
    detectedBulbs[responseList[0]] = responseList

  if readGroup[1]:
    try:
      data = listenSocket.recvfrom(2048)
    except socket.error, e:
      error = e.args[0]
      print(error)

  responseList = processResponse(data)

  if len(responseList):
    detectedBulbs[responseList[0]] = responseList

  print(detectedBulbs)

  for ip in detectedBulbs:
    status =  detectedBulbs[ip]
    if status[3] == "on":
      response = getCronJob(ip, status[1])

      print(response)

      if not(len(response)):
        setCronJob(ip, status[1], CRON_TIMEOUT)

  return detectedBulbs

scanSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# fcntl.fcntl(scanSocket, fcntl.F_SETFL, os.O_NONBLOCK)

listenSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
listenSocket.bind(("", 1982))
# fcntl.fcntl(listenSocket, fcntl.F_SETFL, os.O_NONBLOCK)

mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
listenSocket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

try:
  while True:
    detectedBulbs = executeSearch(scanSocket, listenSocket)
    sleep(WAIT_TIMEOUT)
except KeyboardInterrupt:
  pass