"""端到端验证用 mock 服务：模拟图像检测团队的内部接口。

用法: python examples/mock_server.py  （监听 127.0.0.1:8765）
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _reply(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ct = self.headers.get("Content-Type", "")
        token = self.headers.get("X-API-Token", "")

        if token != "demo-token":
            self._reply({"error": "unauthorized"}, status=401)
            return

        if self.path == "/v1/detect":
            self._reply({
                "objects": [
                    {"name": "cat", "confidence": 0.98, "bbox": [12, 8, 140, 120]},
                    {"name": "sofa", "confidence": 0.87, "bbox": [0, 60, 220, 180]},
                ],
                "_echo": {
                    "content_type": ct,
                    "received_bytes": length,
                    "has_image": b"filename=" in body,
                },
            })
        elif self.path == "/v1/ocr":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                req = {}
            self._reply({
                "text": "示例 OCR 结果",
                "_echo": req,
            })
        else:
            self._reply({"error": "not found"}, status=404)

    def log_message(self, *args) -> None:  # 静默
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
