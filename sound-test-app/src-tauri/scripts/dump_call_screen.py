"""iOS 통화 알림 화면 접근성 덤프 스크립트"""
from appium import webdriver
from appium.options.ios import XCUITestOptions
import xml.etree.ElementTree as ET

opts = XCUITestOptions()
opts.platform_name = "iOS"
opts.udid = "00008150-00110C341E38401C"
opts.no_reset = True
opts.auto_accept_alerts = False

print("Appium 연결 중...")
d = webdriver.Remote("http://127.0.0.1:4724", options=opts)
print("page_source 덤프 중...")
src = d.page_source

with open("/tmp/ios_call_dump.xml", "w") as f:
    f.write(src)

root = ET.fromstring(src)
print("\n===== 접근성 요소 목록 =====\n")
for el in root.iter():
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    label = el.attrib.get("label", "")
    name = el.attrib.get("name", "")
    value = el.attrib.get("value", "")
    vis = el.attrib.get("visible", "")
    acc = el.attrib.get("accessible", "")
    x = el.attrib.get("x", "")
    y = el.attrib.get("y", "")
    w = el.attrib.get("width", "")
    h = el.attrib.get("height", "")
    text = label or name or value
    if text:
        print(f"  [{tag}] label=\"{label}\" name=\"{name}\" visible={vis} acc={acc}  ({x},{y} {w}x{h})")

d.quit()
print("\n완료. XML: /tmp/ios_call_dump.xml")
