import os
import sys
import time
import webbrowser

print("""
1.GTA 6 (New And Fire Sell)
2.MineCraft (New Spear New Mace)
3.TCL (New Phone)
4.Samsung S26 Ultra (New Fire Sell)
5.Hacked Microsoft (Microsoft Hacked)
""")
User = input ("Select Numbers : ")

os.system("clear")

if User =="1":
  url1 = "https://www.google.com/search?sca_esv=255b5630f5566803&sxsrf=AKL5yDhdFDAr9fJDugMaimbmX3pqhiezTA:1795175748093&q=GTA+6+PC+release+date&sa=X&ved=2ahUKEwjQqZjmvpaYAxX2hisGHTV6OssQ1QJ6BAgnEAE&biw=360&bih=686&dpr=2"
  webbrowser.open(url1)
elif User =="2":
  url2 = "https://www.google.com/search?sca_esv=255b5630f5566803&sxsrf=AKL5yDic_XnKUU3BeFH67-Q-96kH7DeaRA:1795176091553&q=MineCraft+Latest+Version+Java&spell=1&sa=X&ved=2ahUKEwiT3_uJwJaYAxUNRvEDHZKkEZcQBSgAegQIDBAB"
  webbrowser.open(url2)
elif User =="3":
  url3 = "https://www.google.com/search?sca_esv=255b5630f5566803&sxsrf=AKL5yDhcpmZowPNnbxr0X_7bjcGlNnIbqQ:1795176168343&q=TCL+Latest+Phone&spell=1&sa=X&ved=2ahUKEwiU1cquwJaYAxU-QvEDHTpDN40QBSgAegQIDBAB&biw=360&bih=686&dpr=2"
  webbrowser.open(url3)
elif User =="4":
  url4 = "https://www.google.com/search?q=Samsung+S26+Ultra"
  webbrowser.open(url4)
elif User =="5":
  url5 = "https://www.google.com/search?q=MicroSoft+Hacked%3F"
  webbrowser.open(url5)
else:
  print ("What")
  sys.exit()