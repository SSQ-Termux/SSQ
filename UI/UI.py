Names = input ("Hey Boss ReEnter Your Name For Humans Check ? ")

import os
import sys
import time
import colorama
from colorama import *
import subprocess

def InstallAPK():
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    APK_PATH = os.path.join(
        BASE_DIR,
        "APK",
        "Box.SSQ.HTU_base.apk"
    )

    if os.path.isfile(APK_PATH):
        subprocess.Popen(["termux-open", APK_PATH])
        print("[+] Opening APK Installer...")
        print("APK Not Installed No Problem PWD : ~/SSQ/APK/$$$")
    else:
        print("[-] APK Not Found!")
        print(APK_PATH)
def sprint(*values, sep=" ", end="\n", delay=0.03):
    text = sep.join(str(value) for value in values) + end

    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        if delay > 0:
            time.sleep(delay)


def sinput(prompt="", delay=0.03):
    sprint(prompt, end="", delay=delay)
    return input()

os.system("clear")

logo = r"""
 ███████╗███████╗ ██████╗
 ██╔════╝██╔════╝██╔═══██╗
 ███████╗███████╗██║ N ██║
 ╚════██║╚════██║██║▄▄ ██║
 ███████║███████║╚██████╔╝
 ╚══════╝╚══════╝ ╚══▀▀═╝

       S S Q  -  T E R M U X
       
"""

for line in logo.splitlines():
    sprint("\033[1;32m" + line + "\033[0m")
    time.sleep(1)

sprint("\033[1;37m[+] Welcome To SSQ \033[0m")
sprint("")
sprint(Fore.RED + "1.SSQ(SMSBOMBER)")
sprint(Fore.RED + "2.SSQ(DDoS)")
sprint(Fore.RED + "3.SSQ(BIRDS)")
sprint(Fore.RED + "4.SSQ(ThorBrowser)")
sprint(Fore.RED + "5.SSQ(CCTVHACK)")
sprint(Fore.RED + "6.SSQ(FlaskChat)")
sprint(Fore.RED + "7.SSQ(NanoGen)")
sprint(Fore.RED + "8.SSQ(HDBChat)")
sprint(Fore.RED + "9.SSQ(HDB)")
sprint(Fore.RED + "10.SSQ(NetScanner)")
sprint(Fore.RED + "11.SSQ(NFCDrop)")
sprint(Fore.RED + "12.SSQ(Op-Commpreesors)")
sprint(Fore.RED + "13.SSQ(UltraFastDownLoadSpeed)")
sprint(Fore.RED + "14.SSQ(WebHack)")
sprint(Fore.RED + "15.SSQ(WordGenPro)")
sprint(Fore.RED + "16.SSQ(Browse My Files)")
sprint(Fore.RED + "17.SSQ(IpOpenPortCheckers)")
sprint(Fore.RED + "18.SSQ(Unknown Browser Ultra Safe)")
sprint(Fore.RED + "19.SSQ(Force Deleter)")
sprint(Fore.RED + "20.SSQ(URL Openers)")
sprint(Fore.RED + "21.Install HTU (APK Already)")
sprint(Fore.RED + "22.SSNews(What's New)")
sprint(Fore.RED + "23.Upgrade To Permum(SSQPro)")
sprint(Fore.RED + "24.Sub(GH/TM/Etaa/Bale/YT)")
sprint(Fore.RED + "25.Exit(SSE-9Pro : Don't Select This)")
sprint("")
User = sinput (Fore.YELLOW + f"{Names} Select Numbers : ")

os.system("clear")

if User == "1":
    os.system("python Tools/SMS/SSQ.py")
elif User == "2":
    os.system("python Tools/DDOS.SSQ.py")
elif User == "3":
    os.system("python Tools/BIRDS/SSQ.py")
elif User == "4":
    os.system("python Tools/TB/SSQ.py")
elif User == "5":
    os.system("python Tools/CCTV/SSQ.py")
elif User == "6":
    os.system("python Tools/FlaskChat/app.py")
elif User == "7":
    os.system("python Tools/NanoGen/main.py.py")
elif User == "8":
    os.system("python Tools/HDBChat/app.py")
elif User == "9":
    os.system("bash Tools/HDB/HDB.sh")
elif User == "10":
    os.system("python Tools/NetScanner/app.py")
elif User == "11":
    os.system("bash Tools/NFCD/NFCDrop.sh")
elif User == "12":
    os.system("python Tools/OPC/iop.py")
elif User == "13":
    os.system("python Tools/UFIS/main.py")
elif User == "14":
    os.system("python Tools/webhack/WebHack.py")
elif User == "15":
    os.system("python Tools/WordGenPro/Ban.py")
elif User == "16":
    os.system("python Tools/BMFs/SSQ.py")
elif User == "17":
    os.system("python Tools/IPCs/IP.py")
elif User == "18":
    os.system("python Tools/UB/UB.py")
elif User == "19":
    os.system("python Tools/RMDIR/RMDIR.py")
elif User == "20":
    os.system("python Tools/URL/URL.py")
elif User == "21":
    InstallAPK()
elif User == "22":
    os.system("python SSNews/SSNews.py")
elif User == "23":
    os.system("python TUP/P.py")
elif User == "24":
    os.system("python Sub/Sub.py")
elif User == "25":
    os.system("python Exit/Exit.py")
else:
  print("Invalid Option!")
  sys.exit()

#Made By Mehrdad Pro Is ReStocked For DownLoad