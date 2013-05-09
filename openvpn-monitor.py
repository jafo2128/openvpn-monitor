#!/usr/bin/env python

# Licensed under GPL v3
# Copyright 2011 VPAC <http://www.vpac.org>
# Copyright 2012, 2013 Marcus Furlong <furlongm@gmail.com>


import getopt
import sys
import socket
import ConfigParser
import locale
from datetime import datetime
import GeoIP
from ipaddr import IPv4Address

CONFIG_FILE = './openvpn-monitor.cfg'
debug = False


def get_config(config_file):
    settings = {}
    vpns = {}
    try:
        f = open(config_file)
    except:
        print "Config file doesn't exist or is unreadable,"
        return default_settings()
    config = ConfigParser.RawConfigParser()
    config.read(config_file)
    sections = []
    try:
        sections = config.sections()
        for section in sections:
            if section == 'OpenVPN-Monitor':
                settings = parse_global_section(config)
            else:
                vpns[section] = parse_vpn_section(config, section)
    except:
        print "Syntax error reading config file."
        return default_settings()
    return settings, vpns


def default_settings():
    print "Using default of localhost:5555"
    settings = {}
    vpns = {}
    settings = {'site': 'Default Site'}
    vpns['Default VPN'] = {'name': 'default', 'host': 'localhost',
                              'port': '5555', 'order': '1'}
    return settings, vpns


def parse_global_section(config):
    global debug
    vars = ['site', 'logo', 'height', 'width', 'lat', 'long', 'maps']
    tmp = {}
    for var in vars:
        try:
            tmp[var] = config.get('OpenVPN-Monitor', var)
        except ConfigParser.NoOptionError:
            pass
    if debug:
        print "=== begin section\n%s\n=== end section" % tmp
    return tmp


def parse_vpn_section(config, section):
    global debug
    tmp = {}
    options = config.options(section)
    for option in options:
        try:
            tmp[option] = config.get(section, option)
            if tmp[option] == -1:
                print("CONFIG: skipping: %s" % option)
        except:
            print("CONFIG: exception on %s!" % option)
            tmp[option] = None
    if debug:
        print "=== begin section\n%s\n=== end section" % tmp
    return tmp


def openvpn_connect(vpn, command):
    global debug
    host = vpn['host']
    port = int(vpn['port'])
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, port))
        vpn['socket_connect'] = True
    except socket.error:
        vpn['socket_connect'] = False
        return False
    s.send(command)
    data = ""
    while 1:
        tmp = s.recv(1024)
        data += tmp
        if data.endswith("END\r\n"):
            break
    s.send('quit\n')
    s.close()
    if debug:
        print "=== begin raw data\n%s\n=== end raw data" % data
    return data


def openvpn_parse_state(data):
    global debug
    state = {}
    for line in data.splitlines():
        tmp = line.split(",")
        if (debug):
            print "=== begin split line\n%s\n=== end split line" % tmp
        if tmp[0].startswith(">INFO") or tmp[0].startswith("END"):
            continue
        else:
            state['identifier'] = tmp[0]
            state['connected'] = tmp[1]
            state['success'] = tmp[2]
            state['local_ip'] = tmp[3]
            if tmp[4]:
                state['remote_ip'] = tmp[4]
                state['type'] = "tap"
            else:
                state['type'] = "tun"
    return state


def openvpn_parse_status(data):
    global debug
    lines = data.splitlines()
    sec_client = False
    sec_routes = False
    sessions = {}
    tap_session = {}
    last_update = ''
    for line in lines:
        tmp = line.split(",")
        if (debug):
            print "=== begin split line\n%s\n=== end split line" % tmp
        if tmp[0] == "GLOBAL STATS":
            break
        if tmp[0] == "Updated":
            last_update = datetime.strptime(tmp[1], "%a %b %d %H:%M:%S %Y")
            continue
        if tmp[0] == "Common Name":
            sec_client = True
            continue
        if tmp[0] == "ROUTING TABLE" or tmp[0] == "Virtual Address":
            sec_routes = True
            sec_client = False
            continue
        session = {}
        if tmp[0] == "TUN/TAP read bytes":
            tap_session['tuntap_read'] = tmp[1]
            continue
        if tmp[0] == "TUN/TAP write bytes":
            tap_session['tuntap_write'] = tmp[1]
            continue
        if tmp[0] == "TCP/UDP read bytes":
            tap_session['tcpudp_read'] = tmp[1]
            continue
        if tmp[0] == "TCP/UDP write bytes":
            tap_session['tcpudp_write'] = tmp[1]
            continue
        if tmp[0] == "Auth read bytes":
            tap_session['auth_read'] = tmp[1]
            sessions['tuntap'] = tap_session
            continue
        if sec_client and not sec_routes:
            session['username'] = tmp[0]
            session['remote_ip'], session['port'] = tmp[1].split(":")
            session['bytes_recv'] = tmp[2]
            session['bytes_sent'] = tmp[3]
            session['connected_since'] = datetime.strptime(tmp[4], "%a %b %d %H:%M:%S %Y")
            sessions[tmp[1]] = session
        if sec_routes and not sec_client:
            sessions[tmp[2]]['local_ip'] = tmp[0]
            sessions[tmp[2]]['last_seen'] = datetime.strptime(tmp[3], "%a %b %d %H:%M:%S %Y")
        if debug:
            if sessions:
                print "=== begin sessions\n%s\n=== end sessions" % sessions
    return sessions


def print_table_headers(headers):
    print "<table><tr>"
    for header in headers:
        print "<th>%s</th>" % header
    print "</tr>"


def openvpn_print_html(vpn):

    gi = GeoIP.open("/usr/share/GeoIP/GeoIPCity.dat", GeoIP.GEOIP_STANDARD)

    if vpn["state"]["connected"] == "CONNECTED":
        connection = "Connection up,"
    else:
        connection = "Connection down,"

    if vpn["state"]["success"] == "SUCCESS":
        pingable = "pingable."
    else:
        pingable = "not pingable."

    print "<div><table><tr><td class=\"left\">%s - %s %s </td><td class=\"right\">[ %s" % (vpn["name"], connection, pingable, vpn["state"]["local_ip"])

    tun_headers = ['Username / Hostname', 'VPN IP Address', 'Remote IP Address', 'Port', 'Location', 'Recv', 'Sent', 'Connected Since', 'Last Ping', 'Time Online']
    tap_headers = ['Tun-Tap-Read', 'Tun-Tap-Write', 'TCP-UDP-Read', 'TCP-UDP-Write', 'Auth-Read']

    vpn_type = vpn['state']['type']
    vpn_sessions = vpn['sessions']

    print vpn_type

    if vpn_type == 'tun':
        print "]</td></tr></table>"
        print_table_headers(tun_headers)
    elif vpn_type == 'tap':
        print " &lt;-&gt; %s]</td></tr></table>" % vpn['state']['remote_ip']
        print_table_headers(tap_headers)

    for key, session in vpn_sessions.items():
        print "<tr>"
        if vpn_type == "tap":
            print "<td>%s</td>" % locale.format('%d', int(session['tuntap_read']), True)
            print "<td>%s</td>" % locale.format('%d', int(session['tuntap_write']), True)
            print "<td>%s</td>" % locale.format('%d', int(session['tcpudp_read']), True)
            print "<td>%s</td>" % locale.format('%d', int(session['tcpudp_write']), True)
            print "<td>%s</td>" % locale.format('%d', int(session['auth_read']), True)
        else:
            country = None
            gir = None
            total_time = str(datetime.now() - session['connected_since'])[:-7]
            bytes_recv = int(session['bytes_recv'])
            bytes_sent = int(session['bytes_sent'])
            print "<td>%s</td>" % session['username']
            print "<td>%s</td>" % session['local_ip']
            print "<td>%s</td>" % session['remote_ip']
            print "<td>%s</td>" % session['port']

            ipaddr = IPv4Address(session['remote_ip'])
            if ipaddr.is_private:
                country = "RFC1918"
            else:
                gir = gi.record_by_addr(session['remote_ip'])
                country = gir['country_code']
            if gir is not None:
                print '<td><img src="%s" title="%s, %s" /></td>' % ('flags/%s.png' % country.lower(), gir['city'], gir['country_name'])
            else:
                if country == "RFC1918":
                    print "<td>RFC1918</td>"
                else:
                    print "<td>Unknown</td>"
            print "<td>%s</td>" % locale.format('%d', bytes_recv, True)
            print "<td>%s</td>" % locale.format('%d', bytes_sent, True)
            print "<td>%s</td>" % str(session['connected_since'].strftime('%d/%m/%Y %H:%M:%S'))
            print "<td>%s</td>" % str(session['last_seen'].strftime('%d/%m/%Y %H:%M:%S'))
            print "<td>%s</td>" % total_time
        print "</tr>"
    print "</table></div><br /><br />"


def google_maps_js(vpns, loc_lat, loc_long):

    gi = GeoIP.open("/usr/share/GeoIP/GeoIPCity.dat", GeoIP.GEOIP_STANDARD)
    sessions = 0
    print "<script type=\"text/javascript\" src=\"https://maps.google.com/maps/api/js?sensor=true\"></script>"
    print "<script type=\"text/javascript\">"
    print "function initialize() {"
    print "var bounds = new google.maps.LatLngBounds();"
    print "var markers = new Array();"
    for vkey, vpn in vpns:
        if 'sessions' in vpn:
            for skey, session in vpn['sessions'].items():
                gir = gi.record_by_addr(session['remote_ip'])
                if gir is not None:
                    print "var latlng = new google.maps.LatLng(%s, %s);" % (gir['latitude'], gir['longitude'])
                    print "bounds.extend(latlng);"
                    print "markers.push(new google.maps.Marker({position: latlng, title: \"%s\\n%s\"}));" % (session['username'], session['remote_ip'])
                    sessions = sessions + 1
    if sessions != 0:
        if sessions == 1:
            print "bounds.extend(new google.maps.LatLng(%s, %s));" % (loc_lat, loc_long)
        print "var myOptions = { zoom: 8, mapTypeId: google.maps.MapTypeId.ROADMAP };"
        print "var map = new google.maps.Map(document.getElementById(\"map_canvas\"), myOptions);"
        print "map.fitBounds(bounds);"
        print "for ( var i=markers.length-1; i>=0; --i ) { markers[i].setMap(map); }"
        print "}"
        print "</script>"
    else:
        print "var latlng = new google.maps.LatLng(%s, %s);" % (loc_lat, loc_long)
        print "var myOptions = { zoom: 8, center: latlng, mapTypeId: google.maps.MapTypeId.ROADMAP };"
        print "var map = new google.maps.Map(document.getElementById(\"map_canvas\"), myOptions);"
        print "}"
        print "</script>"

def google_maps_html():
    print "<div id=\"map_canvas\" style=\"width:100%; height:300px\"></div>"


def html_header(settings, vpns, maps):

    if 'lat' in settings:
        loc_lat = settings['lat']
    else:
        loc_lat = -37.8067
    if 'long' in settings:
        loc_long = settings['long']
    else:
        loc_long = 144.9635

    print "Content-Type: text/html\n"
    print "<!doctype html>"
    print "<html><head><meta charset=\"utf-8\"><title>%s OpenVPN Status Monitor</title>" % settings["site"]
    print "<meta http-equiv='refresh' content='300' />"

    if maps:
        google_maps_js(vpns, loc_lat, loc_long)

    print "<style type=\"text/css\">"
    print "body { font-family: sans-serif; font-size: 12px; background-color: #FFFFFF; margin: auto; }"
    print "h1 { color: #222222; font-size: 20px; text-align: center; padding-bottom: 0; margin-bottom: 0; }"
    print "table { margin: auto; width:900px; border-collapse: collapse; }"
    print "td.left {text-align: left; color: #232355; font-weight: bold; font-size: 14px; }"
    print "td.right {text-align: right; color: #656511; font-weight: bold; font-size: 14px; }"
    print "th { background: #555555; color: white; text-align: left; padding-left: 10px;}"
    print "td { padding: 10px 10px 5px 5px; }"
    print "div { padding: 7px 4px 6px 6px; margin: 0px auto; text-align: center; }"
    print "div.footer { text-align: center; }"
    print "</style></head><body onload=\"initialize()\">"
    if 'logo' in settings:
        print "<div><img class=\"logo\" src=\"%s\" alt=\"logo\" " % settings['logo']
        if 'height' in settings and 'width' in settings:
            print "height=\"%s\" width=\"%s\"" % (settings['height'], settings['width'])
        print "/></div>"
    print "<h1>%s OpenVPN Status Monitor</h1><br />" % settings['site']


def sort_dict(adict):
    keys = adict.keys()
    keys.sort()
    return map(adict.get, keys)


def usage(script_name, exit_code):
    print "%s, [--help] [--debug]" % script_name
    sys.exit(exit_code)


def main():
    global debug

    locale.setlocale(locale.LC_ALL, 'en_GB.UTF-8')

    try:
        opts, args = getopt.getopt(sys.argv[1:], 'h:d', ['help', 'debug'])
    except getopt.GetoptError, err:
        print str(err)
        usage(sys.argv[0], 2)
    for o, a in opts:
        if o in ('-d', '--debug'):
            debug = True
        elif o in ('-h', '--help'):
            usage(sys.argv[0], 0)
        else:
            assert False, 'Unhandled option.'

    settings, vpns = get_config(CONFIG_FILE)

    sort_dict(vpns)

    for key, vpn in vpns.items():

        data = openvpn_connect(vpn, 'state\n')
        if vpn['socket_connect']:
            state = openvpn_parse_state(data)
            vpns[key]['state'] = state

            data = openvpn_connect(vpn, 'status\n')
            sessions = openvpn_parse_status(data)
            vpns[key]['sessions'] = sessions

    if 'maps' in settings and settings['maps'] == 'True':
        maps = True
    else:
        maps = False

    html_header(settings, vpns.items(), maps)

    for key, vpn in vpns.items():

        if vpn['socket_connect']:
            openvpn_print_html(vpn)
        else:
            print "<div><table><tr><td class=\"left\">%s - Connection refused to %s:%s </td>" % (vpn['name'], vpn['host'], vpn['port'])
            print "</tr></table></div><br /><br />"

    if maps:
        google_maps_html()

    if debug:
        print "=== begin vpns\n%s\n=== end vpns" % vpns

    print "<div class=\"footer\">Page automatically reloads every 5 minutes.<br/>Last update: <b>%s</b></div>" % datetime.now().strftime('%a %d/%m/%Y %H:%M:%S')
    print "</body>\n</html>"

if __name__ == '__main__':
    main()
