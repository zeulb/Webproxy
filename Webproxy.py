import socket
import threading
import SocketServer
import sys
import time
import hashlib
import re
from helper import Request, Response

PROXY_HOST = 'localhost'
PROXY_PORT = 3282
BUFFER_SIZE = 4096
CENSOR_FILE = 'censor.txt'
censor_list = []


class ProxyRequestHandler(SocketServer.BaseRequestHandler):

  cache_manifest = {}

  def censor(self, file_name):
    data = ''
    header = ''
    content = ''
    with open(file_name, 'r') as f:
      data = f.read()

      headerIndex = data.find("\r\n\r\n");
      if headerIndex > -1:
        header = data[:headerIndex]
        content = data[headerIndex:]

        for word_re in censor_list:
          content = word_re.sub('---', content)

        content_length = len(content)-4; # minus \r\n\r\n
        header = re.sub("Content-Length: \\d+\r\n", "Content-Length: %d\r\n" % content_length, header)
        
        data = header+content
      else:
        for word_re in censor_list:
          data = word_re.sub('---', data)


    with open(file_name, 'w') as f:
      f.seek(0)
      f.truncate()
      f.write(data)


  def get_from_cache(self, md5):
    self.remote.close()

    timestamp, hash = self.cache_manifest[md5]

    with open(hash, 'r') as f:
      while 1:
        data = f.read(BUFFER_SIZE)
        if data:
          self.request.send(data)
        else:
          break
      self.request.close()


  def cache_response(self, md5, message, timestamp):

    # send the http request
    self.remote.send(message)

    # combine md5 and timestamp to create random hash
    hash = hashlib.md5(md5 + str(timestamp)).hexdigest()

    with open(hash, 'w') as f:
      f.seek(0)
      f.truncate()
      # receive data from remote socket
      modified = True
      censorable = False
      try:
        first_data = True
        while 1:
          data = self.remote.recv(BUFFER_SIZE)

          if first_data:
            response = Response(data)
            
            # check if this file censorable
            try:
              content_type = response.getheader('Content-Type')
              if content_type.startswith('text/html'):
                censorable = True
              if content_type.startswith('text/plain'):
                censorable = True
            except:
              pass

            if response.status == 304:
              # if the first data is 304 (Not modified)
              modified = False
              break
          
          if data:
            f.write(data)
          else:
            break

          first_data = False
      except socket.error:
        pass

      self.remote.close()
    
    if modified or self.cache_manifest.get(md5, None) is None:
      # if not modified
      in_cache = self.cache_manifest.get(md5, None)

      if not in_cache or (in_cache and in_cache[0] < timestamp):
        self.cache_manifest[md5] = (timestamp, hash)
        if censorable and len(self.cache_manifest) > 0:
          self.censor(hash)


  def handle(self):
    try:
      print "Connected:", self.client_address
      # get the http request string
      httpRequest = self.request.recv(BUFFER_SIZE)

      if not httpRequest:
        self.request.close()
        return
      # get information about the request
      requestInfo = Request(httpRequest, self.client_address).get_info()

      try:
        # make connection with remote address
        self.remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.remote.connect((requestInfo.get('host', ''), requestInfo.get('port', 0)))
        self.remote.setblocking(0)
        self.remote.settimeout(3.0)
        # request

        md5 = str(hashlib.md5(httpRequest).hexdigest())

        in_cache = self.cache_manifest.get(md5, None)

        # check if cache available
        if in_cache and requestInfo['method'] == 'GET':
          # check if modified, only check on get method
          httpRequest = httpRequest[:-2] + 'If-Modified-Since: '+Request().date_time_string(in_cache[0])+'\r\n\r\n'
        
        self.cache_response(md5, httpRequest, requestInfo['time'])
        self.get_from_cache(md5)
        self.request.close()

        
      except socket.error as msg:
        # send 502 message
        if self.request:
          self.request.send(Request().get_error(502))
          self.request.close()

        if self.remote:
          self.remote.close()

    except KeyboardInterrupt:
      self.request.close()  


if __name__ == '__main__':
  if len(sys.argv) == 2:
    PROXY_PORT = int(sys.argv[1])

  # import censor list
  try:
    with open(CENSOR_FILE, 'r') as f:
      for word in f:
        censor_list.append(re.compile(re.escape(word.strip()), re.IGNORECASE))
  except:
    pass

  SocketServer.ThreadingTCPServer.allow_reuse_address=True
  server = SocketServer.ThreadingTCPServer((PROXY_HOST, PROXY_PORT), ProxyRequestHandler)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    server.shutdown()
