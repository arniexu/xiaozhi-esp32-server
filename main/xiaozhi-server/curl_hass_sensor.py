import subprocess
import json

# 示例：请替换为你的 Home Assistant 地址和 token
url = "http://192.168.100.143:8123/api/states/sensor.miaomiaoc_cn_blt_3_1m2cf17fcck00_t9_relative_humidity_p_3_1002"
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJlNTQ4MWE5MWQwZGE0N2ViODFkOTJkM2IyN2M3NDIwMSIsImlhdCI6MTc1NTUxOTg2OSwiZXhwIjoyMDcwODc5ODY5fQ.MDam1zc9E1Iyf46HF8A5UQJcJvD94L9U74K1Kh6j0qc"

curl_cmd = [
    "curl",
    "-H", f"Authorization: Bearer {token}",
    "-H", "Content-Type: application/json",
    url
]

result = subprocess.run(curl_cmd, capture_output=True, text=True)
if result.returncode == 0:
    try:
        data = json.loads(result.stdout)
        print("Sensor 信息:", json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print("解析 JSON 失败:", e)
else:
    print("请求失败:", result.stderr)
