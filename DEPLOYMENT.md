# Deployment Information

## Public URL

https://production-ai-agent-qxc3.onrender.com

## Platform

**Render** (Blueprint `k5-day14-agent`, region Singapore, gói Free). Deploy agent Part 6 trong `06-lab-complete/` (theo CP6), từ nhánh `feat/part6-production-agent`, commit `cb614e2`.

| Service | Loại | Runtime | Trạng thái |
|---|---|---|---|
| `production-ai-agent` | Web Service | Docker (`06-lab-complete/Dockerfile`, multi-stage) | Deployed / Live |
| `agent-redis` | Key Value | Valkey 8 (tương thích Redis) | Available |

Blueprint path: `06-lab-complete/render.yaml` (`rootDir: 06-lab-complete`, `healthCheckPath: /health`).

> Railway (Exercise 3.1) không dùng được: `railway init` trả `Your trial has expired. Please select a plan to continue using Railway.` Mình không nhập thẻ mà chuyển sang Render.
>
> Gói Free của Render tắt service khi không có request, nên lần gọi đầu sau một lúc không dùng có thể chậm ~50 giây.

## Test Commands

Đặt `BASE` là URL ở trên và `AGENT_API_KEY` là key trên Render (Environment → `AGENT_API_KEY`). Mỗi lệnh chỉ in mã HTTP, không lộ key.

```bash
BASE=https://production-ai-agent-qxc3.onrender.com

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy ngày 26/11/2026: **200, 200, 401, 200** (ảnh `screenshots/test.png`).

### Health check

```text
$ curl https://production-ai-agent-qxc3.onrender.com/health
{"status":"ok","environment":"production"}

$ curl https://production-ai-agent-qxc3.onrender.com/ready
{"status":"ready","redis":"ok"}
```

### API test (có xác thực)

```text
$ curl -X POST $BASE/ask -H "X-API-Key: $AGENT_API_KEY" -H "Content-Type: application/json" \
       -d '{"question": "What is docker?"}'
{"question":"What is docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

# Thiếu key hoặc sai key
{"detail":"Invalid or missing API key"}      → 401
```

### Kiểm tra thêm

- Rate limit (`RATE_LIMIT_PER_MINUTE=10`, state trong Key Value): sau 2 request trước đó, gửi 12 request liên tiếp → `200 ×8, 429 ×4` (request thứ 11 trong 60 giây bị chặn).
- `GET /metrics` → 404 (không có endpoint này trên agent Part 6).
- `python check_production_ready.py --public-url https://production-ai-agent-qxc3.onrender.com` → `✅ Public URL: GET .../health → 200`, mục 12 đạt toàn bộ.

## Environment Variables Set

Đặt trên Render (khai báo trong `render.yaml`), **không** ghi trong code:

| Biến | Giá trị / nguồn |
|---|---|
| `AGENT_API_KEY` | `generateValue: true`: Render tự sinh key ngẫu nhiên (44 ký tự), không nằm trong repo |
| `REDIS_URL` | `fromService` → `agent-redis`, `property: connectionString` (URL nội bộ của Key Value) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |
| `PORT` | Render tự cấp; `CMD` của Dockerfile nghe theo `${PORT:-8000}` |
| `LOG_LEVEL` | Không đặt, dùng mặc định `INFO` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png): Blueprint `k5-day14-agent`, 2 service Deployed / Available
- [Service running](screenshots/running.png): `production-ai-agent` Live, Docker, deploy `cb614e2`
- [Test results](screenshots/test.png): 4 lệnh tự kiểm CP6
