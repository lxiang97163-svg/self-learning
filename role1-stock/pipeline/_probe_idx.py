import os
import requests
os.environ.pop("HTTP_PROXY", None)
r = requests.get("http://qt.gtimg.cn/q=sh000001", timeout=10, proxies={"http": None, "https": None})
r.encoding = "gbk"
line = r.text.split(";")[0]
inner = line.split('="', 1)[1].split('"', 1)[0]
p = inner.split("~")
for i, v in enumerate(p[:50]):
    print(i, repr(v)[:80])
