import socket
import time
import xml.etree.ElementTree as ET

try:
    # Python 3
    from urllib.request import urlopen, Request
    from urllib.parse import urlparse, urljoin
except ImportError:
    # Python 2
    from urllib2 import urlopen, urlparse, Request
    from urlparse import urljoin

IFACE = '0.0.0.0'
SSDP_MCAST_ADDR = '239.255.255.250'
SSDP_PORT = 1900
TIME_OUT = 1

commands = {
    'power': 'NRC_POWER-ONOFF',
    'vol_up': 'NRC_VOLUP-ONOFF',
    'vol_down': 'NRC_VOLDOWN-ONOFF',
    'mute': 'NRC_MUTE-ONOFF',
    'num': 'NRC_D{}-ONOFF',
    'tv': 'NRC_TV-ONOFF',
    'toggle_3D': 'NRC_3D-ONOFF',
    'toggle_SDCard': 'NRC_SD_CARD-ONOFF',
    'red': 'NRC_RED-ONOFF',
    'green': 'NRC_GREEN-ONOFF',
    'yellow': 'NRC_YELLOW-ONOFF',
    'blue': 'NRC_BLUE-ONOFF',
    'vtools': 'NRC_VTOOLS-ONOFF',
    'cancel': 'NRC_CANCEL-ONOFF',
    'option': 'NRC_SUBMENU-ONOFF',
    'return': 'NRC_RETURN-ONOFF',
    'enter': 'NRC_ENTER-ONOFF',
    'right': 'NRC_RIGHT-ONOFF',
    'left': 'NRC_LEFT-ONOFF',
    'up': 'NRC_UP-ONOFF',
    'down': 'NRC_DOWN-ONOFF',
    'display': 'NRC_DISP_MODE-ONOFF',
    'menu': 'NRC_MENU-ONOFF',
    'connect': 'NRC_INTERNET-ONOFF',
    'link': 'NRC_VIERA_LINK-ONOFF',
    'guide': 'NRC_EPG-ONOFF',
    'text': 'NRC_TEXT-ONOFF',
    'subtitles': 'NRC_STTL-ONOFF',
    'info': 'NRC_INFO-ONOFF',
    'index': 'NRC_INDEX-ONOFF',
    'hold': 'NRC_HOLD-ONOFF',
    'ch_up': 'NRC_CH_UP-ONOFF',
    'ch_down': 'NRC_CH_DOWN-ONOFF',
    'input': 'NRC_CHG_INPUT-ONOFF',
    'last_view': 'NRC_R_TUNE-ONOFF'
}

class Viera(object):
    def __init__(self, hostname, control_url, service_type):
        self.hostname = hostname
        self.control_url = control_url
        self.service_type = service_type
        self.throttle = .5
        self.last_called = time.time()

        for name, key in commands.items():
            if name == 'num':
                setattr(self, name, self.send_num(key))
            else:
                setattr(self, name, self.send_key(key))

    @staticmethod
    def discover():
        socket = Viera.create_socket( IFACE, SSDP_PORT)
        Viera.send_request(socket)
        responses = Viera.receive_responses(socket)
        responses = (r for r in responses if 'Panasonic' in r)
        urls = (Viera.parse_response(r) for r in responses)
        data = ((url, urlopen(url).read()) for url in urls)

        return list((Viera.parse_description(*d) for d in data))

    @staticmethod
    def create_socket(ip, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(TIME_OUT)
        sock.bind((ip, port))

        return sock

    @staticmethod
    def send_request(socket):
        header = 'M-SEARCH * HTTP/1.1'
        fields = (
            ('ST', 'urn:panasonic-com:device:p00RemoteController:1'),
            ('MX', '1'),
            ('MAN', '"ssdp:discover"'),
            ('HOST', '239.255.255.250:1900'),
        )

        packet = '\r\n'.join([header] + [': '.join(pair) for pair in fields]) + '\r\n'
        packet = packet.encode('utf-8')

        socket.sendto(packet, (SSDP_MCAST_ADDR, SSDP_PORT))

    @staticmethod
    def receive_responses(sock):
        responses = []
        try:
            while True:
                data = sock.recv(1024)
                data = data.decode('utf-8')
                responses.append(data)
        except socket.timeout:
            # Done receiving responses
            pass

        return responses

    @staticmethod
    def parse_response(data):
        for line in data.splitlines():
            parts = line.split(': ')
            if len(parts) > 1 and parts[0] == 'LOCATION':
                return parts[1]

    @staticmethod
    def parse_description(url, data):
        root = ET.fromstring(data)
        service = root.find('./{urn:schemas-upnp-org:device-1-0}device/'
                               '{urn:schemas-upnp-org:device-1-0}serviceList/'
                               '{urn:schemas-upnp-org:device-1-0}service')

        if service is None:
            raise NoServiceDescriptionError

        service_type = service.find('./{urn:schemas-upnp-org:device-1-0}serviceType').text
        control_url = urljoin(url, service.find('./{urn:schemas-upnp-org:device-1-0}controlURL').text)
        hostname = urlparse(url).netloc

        return Viera(hostname, control_url, service_type)

    def send_num(self, key):
        def func(number):
            for digit in str(number):
                self.send_key(key.format(digit))()

        return func

    def send_key(self, key):
        def func():
            time_last_call = time.time() - self.last_called
            if time_last_call < self.throttle:
                time.sleep(self.throttle - time_last_call)
                self.last_called = time.time()

            name = 'X_SendKey'
            params = '<X_KeyEvent>{}</X_KeyEvent>'.format(key)

            soap_body = (
                '<?xml version="1.0"?>'
                '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope" SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                '<SOAP-ENV:Body>'
                '<m:{name} xmlns:m="{service_type}">'
                '{params}'
                '</m:{name}>'
                '</SOAP-ENV:Body>'
            '</SOAP-ENV:Envelope>'
            ).format(
                name=name,
                service_type=self.service_type,
                params=params
            )

            soap_body = soap_body.encode('utf-8')

            headers = {
                'Host': self.hostname,
                'Content-Length': len(soap_body),
                'Content-Type': 'text/xml',
                'SOAPAction': '"{}#{}"'.format(self.service_type, name),
            }

            req = Request(self.control_url, soap_body, headers)
            result = urlopen(req).read()

        return func

