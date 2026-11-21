import os
import sys
import time
import webbrowser

print("""
1.YouTube
2.GitHub
3.Etaa
4.Telegram
5.WebSite
""")
User = input ("Select Numbers : ")

os.system("clear")

if User =="1":
  url1 = "https://youtube.com/@mehrdadssq"
  webbrowser.open(url1)
elif User =="2":
  url2 = "https://github.com/SSQ-Termux"
  webbrowser.open(url2)
elif User =="3":
  url3 = "https://eitaa.com/SSQTermux"
  webbrowser.open(url3)
elif User =="4":
  print ("I'm Not Install Telegram")
elif User =="5":
  print ("I'm No Money For Buy A Site")
else:
  print ("What")
  sys.exit()