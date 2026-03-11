#!/usr/bin/env python3

import sys
import os
import time
import serial
import threading
import subprocess
import psutil

os_is_openwrt = False

fm350_idproduct = 0x7127
fm350_idvendor = 0x0e8d
fm350_openwrt_interface_name = "wwan_fm350"

fm350_ipaddr = ""

class SerialReader:
    def __init__(self, port, baudrate=115200):
        self.rbuffer = str()
        self.rbuffer_lock = threading.Lock()
        self.thread = None
        self.ser = None

        try:
            self.ser = serial.Serial(port, baudrate, timeout=0)
            self.running = True
            # Create and start the thread
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
        except Exception as e:
            print(e)

    def _read_loop(self):
        if self.ser is None:
            return

        while self.running:
            if self.ser.in_waiting > 0:
                data = self.ser.readall().decode('utf-8')

                with self.rbuffer_lock:
                    if len(self.rbuffer) > 1048576:
                        self.rbuffer = str()

                    self.rbuffer += data

            time.sleep(0.01)

    def send_data(self, message):
        if self.ser is None:
            return

        self.ser.write(f"{message}\r\n".encode('utf-8'))

    def recv_data(self):
        ret = str()
        with self.rbuffer_lock:
            ret = self.rbuffer
            self.rbuffer = str()

        return ret

    def recv_data_with_timeout(self, timeout=1):
        ret = str()
        start_time = time.monotonic()

        while time.monotonic() < start_time + timeout:
            with self.rbuffer_lock:
                if len(self.rbuffer) > 0:
                    ret = self.rbuffer
                    self.rbuffer = str()
                    break
            time.sleep(0.1)

        return ret

    def recv_data_clear(self):
        with self.rbuffer_lock:
            self.rbuffer = str()

    def close(self):
        self.running = False

        if self.thread is not None:
            self.thread.join()

        if self.ser is not None:
            self.ser.close()

def fm350_dial_prepare(sr):
    sr.recv_data_clear()
    sr.send_data("AT+GTFCCLOCKMODE?")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()

    if "+GTFCCLOCKMODE: 2" in sbuf or "+GTFCCLOCKMODE: 1" in sbuf:
        print("FCC lock detected, try to unlock and reset modem...")
        sr.recv_data_clear()
        sr.send_data("AT+GTFCCLOCKMODE=0")
        sbuf = sr.recv_data_with_timeout().strip()

        sr.recv_data_clear()
        sr.send_data("AT+CFUN=1,1")
        time.sleep(1)

        return False

    sr.recv_data_clear()
    sr.send_data("AT+GTDUALSIM=0")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()

    sr.recv_data_clear()
    sr.send_data("AT+CPIN?")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()

    if "READY" in sbuf:
        sr.recv_data_clear()
        sr.send_data("AT+CFUN=1")
        time.sleep(1)
        sbuf = sr.recv_data_with_timeout(timeout=5).strip()
        return True

    if "ERROR" in sbuf:
        print("Failed to access SIM card: {0}".format(sbuf))
        return False

    if "SIM_PIN" in sbuf:
        print("SIM card requires PIN code, please unlock card first!")
        return False

    print("SIM card error: {0}".format(sbuf))

    return False


def fm350_at_dial(sr, pdp_index, apn_str):
    sr.recv_data_clear()
    sr.send_data("AT+COPS=0,0")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout(timeout=5).strip()

    sr.recv_data_clear()
    sr.send_data('AT+CGDCONT={0},"IP","{1}"'.format(pdp_index, apn_str))
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()

    if not "OK" in sbuf:
        sr.close()
        print("AT command AT+CGDCONT failed: {0}".format(sbuf))
        sys.exit(6)

    sr.recv_data_clear()
    sr.send_data("AT+CGACT=1,{0}".format(pdp_index))
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()

    if not "OK" in sbuf:
        print("AT command AT+CGACT failed: {0}".format(sbuf))

def fm350_at_watch_signal_info(sr, iface, pdp_index):
    rssi_raw = 99
    rscp_raw = 255
    rsrq_raw = 255
    rsrp_raw = 255
    ss_rsrq_raw = 255
    ss_rsrp_raw = 255
    signal_type = 0
    rssi = -255
    rscp = -255
    rsrq = -255
    rsrp = -255

    sr.recv_data_clear()
    sr.send_data("AT+ERAT?")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()
    if "OK" in sbuf:
        pos = sbuf.find("+ERAT: ")
        if pos >= 0:
            inforaw = sbuf[pos+7:]
            infolist = inforaw.split(",")
            if len(infolist) >= 2:
                try:
                    signal_type = int(infolist[0])
                except:
                    pass

    sr.recv_data_clear()
    sr.send_data("AT+CSQ")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()
    if "OK" in sbuf:
        pos = sbuf.find("+CSQ: ")
        if pos >= 0:
            inforaw = sbuf[pos+6:]
            infolist = inforaw.split(",")
            if len(infolist) >= 2:
                try:
                    rssi_raw = int(infolist[0])
                except:
                    pass

    if rssi_raw >= 0 and rssi_raw < 32:
        rssi = -113 + rssi_raw * 2

    sr.recv_data_clear()
    sr.send_data("AT+CESQ")
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()
    if "OK" in sbuf:
        pos = sbuf.find("+CESQ: ")
        if pos >= 0:
            inforaw = sbuf[pos+7:]
            infolist = inforaw.split(",")
            if len(infolist) >= 9:
                try:
                    rssi_raw = int(infolist[0])
                    rscp_raw = int(infolist[2])
                    rsrq_raw = int(infolist[4])
                    rsrp_raw = int(infolist[5])
                    ss_rsrq_raw = int(infolist[6])
                    ss_rsrp_raw = int(infolist[7])
                except:
                    pass

    if rssi_raw >= 0 and rssi_raw < 64:
        rssi = -111 + rssi_raw

    if rscp_raw >= 0 and rscp_raw < 97:
        rscp = -121 + rscp_raw

    if rsrq_raw >= 0 and rsrq_raw < 35:
        rsrq = -20 + 0.5 * rsrq_raw

    if rsrp_raw >= 0 and rsrp_raw < 98:
        rsrp = -141 + rsrp_raw

    if ss_rsrq_raw >= 0 and ss_rsrq_raw < 127:
        rsrq = -43.5 + 0.5 * ss_rsrq_raw

    if ss_rsrp_raw >= 0 and ss_rsrp_raw < 127:
        rsrp = -157 + ss_rsrp_raw

    if signal_type >= 2 and signal_type < 7:
        print("CMD=SIGNALINFO,MODE=WCDMA,RSSI={0}".format(rssi))
    elif signal_type >= 7 and signal_type < 10:
        print("CMD=SIGNALINFO,MODE=LTE,RSSI={0}".format(rssi))
    elif signal_type <= 14:
        print("CMD=SIGNALINFO,MODE=NR5G-NSA,RSSI={0},RSCP={1},RSRQ={2},RSRP={3}".format(rssi, rscp, rsrq, rsrp))

def fm350_at_watch_ipaddr(sr, iface, pdp_index):
    global fm350_ipaddr
    ipaddr = ""

    sr.recv_data_clear()
    sr.send_data('AT+CGPADDR={0}'.format(pdp_index))
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()

    if not "OK" in sbuf:
        print("AT command AT+CGPADDR failed: {0}".format(sbuf))
        return False

    strlist = sbuf.split(",")
    if len(strlist) < 2:
        return False

    ipaddr = strlist[1].strip('"')

    if len(ipaddr) == 0:
        return False

    ipparts = ipaddr.split(".")
    if len(ipparts) != 4:
        return False

    if fm350_ipaddr == ipaddr:
        return True

    fm350_ipaddr = ipaddr
    netmask = "255.255.255.0"
    gateway = ipparts[0] + "." + ipparts[1] + "." + ipparts[2] + ".1"
    dnslist = ["223.5.5.5", "119.29.29.29"]

    sr.recv_data_clear()
    sr.send_data('AT+GTDNS={0}'.format(pdp_index))
    time.sleep(1)
    sbuf = sr.recv_data_with_timeout().strip()
    sbufl1 = sbuf.split("\n")
    strlist = sbufl1[0].strip().split(",")
    dns1 = ""
    dns2 = ""

    dnslist_len = len(strlist)

    if dnslist_len > 1:
        dns1 = strlist[1].strip('"')

    if dnslist_len > 2:
        dns2 = strlist[2].strip('"')

    if len(dns2) > 0:
        dnslist.insert(0, dns2)

    if len(dns1) > 0:
        dnslist.insert(0, dns1)

    print("IP {0}, Netmask {1}, Gateway {2}, DNS {3}".format(ipaddr, netmask, gateway, dnslist))

    if os_is_openwrt:
        result = subprocess.run(
            "uci -q get network.{0}".format(fm350_openwrt_interface_name),
            capture_output=True, text=True, shell=True)
        if result.returncode != 0 or result.stdout.strip() != "interface":
            os.system("uci set network.{0}=interface".format(fm350_openwrt_interface_name))

        os.system("uci set network.{0}.proto='static'".format(fm350_openwrt_interface_name))
        os.system("uci set network.{0}.metric=14".format(fm350_openwrt_interface_name))
        os.system("uci set network.{0}.ifname={1}".format(fm350_openwrt_interface_name, iface))
        os.system("uci set network.{0}.device={1}".format(fm350_openwrt_interface_name, iface))

        os.system("uci set network.{0}.ipaddr='{1}'".format(fm350_openwrt_interface_name, ipaddr))
        os.system("uci set network.{0}.netmask='{1}'".format(fm350_openwrt_interface_name, netmask))
        os.system("uci set network.{0}.gateway='{1}'".format(fm350_openwrt_interface_name, gateway))
        os.system("uci set network.{0}.peerdns='0'".format(fm350_openwrt_interface_name))
        os.system("uci -q del network.{0}.dns".format(fm350_openwrt_interface_name))

        os.system("uci add_list network.{0}.dns='{1}'".format(fm350_openwrt_interface_name, dnslist[0]))
        os.system("uci add_list network.{0}.dns='{1}'".format(fm350_openwrt_interface_name, dnslist[1]))
        os.system("uci commit network")
        os.system("ifdown {0}".format(fm350_openwrt_interface_name))
        os.system("ifup {0}".format(fm350_openwrt_interface_name))

        fw_ready = False
        result = subprocess.run("uci show firewall | grep \"name='wan'\"",
            capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            res_parts = result.stdout.strip().split(".")
            if len(res_parts) >= 3:
                fw_interfaces = []
                fw_zone_base = res_parts[0] + "." + res_parts[1]
                result = subprocess.run("uci -q get {0}.network".format(fw_zone_base), capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    fw_interfaces = result.stdout.strip().split(" ")
                    if fm350_openwrt_interface_name in fw_interfaces:
                        fw_ready = True

                if not fw_ready:
                    os.system("uci -q del {0}.network".format(fw_zone_base))
                    for fw_interface in fw_interfaces:
                        os.system("uci add_list {0}.network={1}".format(fw_zone_base, fw_interface))
                    os.system("uci add_list {0}.network={1}".format(fw_zone_base, fm350_openwrt_interface_name))
                    os.system("uci commit firewall")
                    os.system("/etc/init.d/firewall restart")

            else:
                print("Cannot parse firewall zone configuration!")
        else:
            print("Cannot find WAN zone in firewall!")

    else:
        os.system("ip addr add {0}/24 dev {1}".format(ipaddr, iface))
        os.system("ip route add default via {0} dev {1}".format(gateway, iface))
        os.system("resolvconf -d {0}".format(iface))
        for dns_str in dnslist:
            os.system("echo 'nameserver {0}' | resolvconf -a {1}".format(dns_str, iface))

    return True


def fm350_at_watch(sr, iface, pdp_index):
    while True:
        fm350_at_watch_signal_info(sr, iface, pdp_index)
        if not fm350_at_watch_ipaddr(sr, iface, pdp_index):
            break
        time.sleep(1)


def main():
    global os_is_openwrt
    fm350_usbsysfs_root = ""
    usbsysfs_root = "/sys/bus/usb/devices"
    pdp_index = 3

    usbdirs = os.listdir(usbsysfs_root)
    for usbdir in usbdirs:
        usbfulldir = os.path.join(usbsysfs_root, usbdir)
        idproduct_file = os.path.join(usbfulldir, "idProduct")
        idvendor_file = os.path.join(usbfulldir, "idVendor")
        idproduct = 0
        idvendor = 0

        try:
            with open(idproduct_file, 'r', encoding="ascii") as f:
                idproduct_str = f.read()
                idproduct = int(idproduct_str, 16)

            with open(idvendor_file, 'r', encoding="ascii") as f:
                idvendor_str = f.read()
                idvendor = int(idvendor_str, 16)
        except:
            pass

        if idproduct == fm350_idproduct and idvendor == fm350_idvendor:
            fm350_usbsysfs_root = usbfulldir
            break

    if len(fm350_usbsysfs_root) == 0:
        print("No FM350 modem detected!")
        sys.exit(1)
        return

    print("FM350 modem detected, searching interface and serial port...")

    if os.path.isfile("/sbin/uci") or os.path.isfile("/usr/sbin/uci"):
        os_is_openwrt = True

    modem_manager_running = False
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == "ModemManager":
            modem_manager_running = True

    if modem_manager_running:
        print("ModemManager detected, stopping service...")

        if os_is_openwrt:
            os.system("/etc/init.d/ModemManager stop")
        else:
            os.system("systemctl stop ModemManager")

    serialports = []
    iface = ""

    usbdirs = os.listdir(fm350_usbsysfs_root)
    for usbdir in usbdirs:
        usbfulldir = os.path.join(fm350_usbsysfs_root, usbdir)
        if not os.path.isdir(usbfulldir):
            continue

        usbsubdirs = os.listdir(usbfulldir)
        for usbsubdir in usbsubdirs:
            if usbsubdir == "net":
                usbsubfulldir = os.path.join(usbfulldir, usbsubdir)
                ifaces = os.listdir(usbsubfulldir)

                if(len(ifaces) > 0):
                    iface = ifaces[0]

            if usbsubdir.startswith("ttyUSB"):
                serialports.append(os.path.join("/dev", usbsubdir))

    if len(iface) == 0 or len(serialports) == 0:
        print("No serial port or interfaces detected for FM350 modem, please check device driver!")
        sys.exit(2)
        return

    serialports.sort()
    serialport = ""
    sphandle = None

    for sport in serialports:
        sr = SerialReader(sport)
        if sr is None:
            continue

        sr.send_data("")
        time.sleep(0.5)
        sr.recv_data_clear()

        sr.send_data("AT")
        time.sleep(1)
        sbuf = sr.recv_data_with_timeout().strip()

        if "OK" in sbuf:
            serialport = sport
            sphandle = sr
            break

        sr.close()

    if sphandle is not None:
        print("Interface {0} and serial port {1} detected.".format(iface, serialport))
    else:
        print("No serial port available for commands, please check device driver!")
        sys.exit(3)
        return

    if not fm350_dial_prepare(sphandle):
        print("Failed to do preparation for dialout!")
        sys.exit(4)

    fm350_at_dial(sphandle, pdp_index, "cbnet")
    fm350_at_watch(sphandle, iface, pdp_index)

if __name__ == "__main__":
    main()
