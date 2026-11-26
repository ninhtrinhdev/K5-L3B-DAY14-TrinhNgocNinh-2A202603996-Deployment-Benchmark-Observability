# Day 14 Lab — Mission Answers

> **Môi trường chạy:** Windows 11 + Docker Desktop 29.5.2. Máy chỉ có Python 3.14, chưa có wheel cho các thư viện của lab, nên các app Python ở Part 1, 4, 5 được chạy trong container `python:3.11-slim` có cài đủ requirements (Linux, nên SIGTERM hoạt động thật). Các lệnh `curl` dưới đây chạy bên trong container đó, cổng `8000` là cổng của app. Part 2 và Part 5 (Docker Compose) chạy trực tiếp trên Docker Desktop.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | Hardcode secret: `OPENAI_API_KEY = "sk-..."` và `DATABASE_URL` chứa mật khẩu `password123` | 17–18 | Push lên GitHub là lộ key và mật khẩu DB; đổi key phải sửa code và deploy lại |
| 2 | Log ra secret: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log của mọi request (đã thấy trong stdout ở Ex 1.2) |
| 3 | Dùng `print()` thay vì logging, in nguyên nội dung câu hỏi và câu trả lời | 33, 38 | Không có level, không parse được, lộ dữ liệu người dùng vào log |
| 4 | Config cố định trong code: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Không đổi được theo môi trường; production cũng chạy chế độ debug |
| 5 | Không có `/health` | 42 | Platform không biết app chết để restart (gọi thử trả **404**) |
| 6 | `host="localhost"` | 51 | Chạy trong container thì bên ngoài không gọi vào được |
| 7 | `port=8000` cố định, không đọc biến `PORT` | 52 | Railway/Render cấp port qua `PORT` → app nghe sai port, deploy fail |
| 8 | `reload=True` luôn bật | 53 | Tốn CPU theo dõi file, process cha/con phức tạp, không dành cho production |
| 9 | Không có lifespan / xử lý SIGTERM | — | Bị tắt giữa chừng thì cắt ngang request, không đóng kết nối |
| 10 | `/ask` nhận `question` qua query string, không giới hạn độ dài | 30–31 | Câu hỏi nằm trên URL nên bị ghi vào access log và log của proxy |

### Exercise 1.2: Chạy bản develop

```text
$ python app.py
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
[HTTP 200]

$ curl http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
[HTTP 422]

$ curl http://localhost:8000/health
{"detail":"Not Found"}
[HTTP 404]
```

Stdout của app (thấy rõ secret bị in ra):

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
Starting agent on localhost:8000...
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
INFO:     127.0.0.1:59706 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Nhận xét:** app chạy được nhưng chưa sẵn sàng cho production. Lệnh JSON trong `CODE_LAB.md` trả 422 vì `ask_agent(question: str)` là query parameter, nên phải gọi `?question=...`.

### Exercise 1.3: So sánh develop và production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hằng số trong code (`DEBUG = True`, key, DB URL) | `config.py` đọc mọi giá trị từ env, có `validate()` | Cùng một image chạy được ở dev/staging/prod chỉ bằng đổi env. `validate()` fail ngay khi thiếu config: chạy `ENVIRONMENT=production` mà không có `AGENT_API_KEY` thì app dừng với `ValueError: AGENT_API_KEY must be set in production!` |
| Secrets | Key trong code và bị `print` ra log | Lấy từ env, log chỉ ghi `question_length`, không ghi key hay nội dung | Không commit secret lên git, không lộ secret qua log |
| Host / Port | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` từ env | Container và cloud cần bind `0.0.0.0` để nhận kết nối từ ngoài; Railway/Render cấp port qua `PORT` |
| Health check | Không có (`/health` → 404) | `/health` (liveness), `/ready` (readiness), `/metrics` | Platform dùng `/health` để biết khi nào restart; load balancer dùng `/ready` để chỉ gửi traffic vào instance đã sẵn sàng |
| Logging | `print()` | `logging` với format dạng JSON | Log có cấu trúc thì search, lọc, alert được trên Loki/Datadog |
| Shutdown | Đột ngột | Lifespan: `is_ready=False` rồi dọn dẹp | Request đang chạy được hoàn thành, không mất dữ liệu. Đã thử `kill -TERM`: log ra `Shutting down → Application shutdown complete`, process tự thoát |
| Reload / Debug | `reload=True` luôn bật | Chỉ reload khi `DEBUG=true` | Production không cần theo dõi file thay đổi |

**Những điểm phát hiện thêm khi chạy thật bản production:**

1. **Log JSON không hiện ra.** `config.py` gọi `logging.warning(...)` lúc import, nên root logger đã được cấu hình (level WARNING, format mặc định) trước khi `app.py` gọi `logging.basicConfig(...)`. Vì vậy `basicConfig` không còn tác dụng, mọi `logger.info(json.dumps(...))` bị bỏ. Log thật chỉ có `WARNING:root:OPENAI_API_KEY not set — using mock LLM` và log của uvicorn.
2. **Format "JSON" vẫn không phải JSON hợp lệ.** Khi `basicConfig` có tác dụng (như ở `02-docker/production/main.py`), dòng log thành `{"time":"...","level":"INFO","msg":"{"event": "request", "q_len": 21}"}`: chuỗi JSON bị nhét vào trong dấu nháy, nên parser sẽ lỗi. Cách đúng là tự viết `logging.Formatter` gọi `json.dumps` cho cả bản ghi (đã làm ở Part 6).
3. **Graceful shutdown thực ra do uvicorn và lifespan làm, không phải `handle_sigterm`.** Trong lúc chạy, `uvicorn.run()` dùng handler SIGTERM của chính nó; handler tự viết chỉ được gọi sau khi server đã tắt xong (thấy rõ ở Ex 5.2). Ở đây dòng `Received SIGTERM` cũng không hiện vì `logger.info` bị bỏ do lỗi logging ở điểm 1.
4. **`.env` không được đọc.** `CODE_LAB.md` bảo `cp .env.example .env`, nhưng code không gọi `load_dotenv()` (dù `python-dotenv` có trong requirements), nên giá trị trong `.env` không có tác dụng nếu không export ra môi trường.

---

## Part 2: Docker

### Exercise 2.1: Đọc `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Python đầy đủ trên Debian (có sẵn gcc, header, công cụ build). Đây là môi trường nền để build image app, nhưng rất nặng.
2. **Working directory:** `WORKDIR /app`, thư mục làm việc mặc định trong container. Các lệnh `COPY`, `RUN`, `CMD` sau đó chạy tương đối từ `/app`, code nằm ở `/app`.
3. **Tại sao `COPY requirements.txt` trước:** để tận dụng Docker layer cache. Layer `pip install` chỉ build lại khi `requirements.txt` đổi. Sửa code (`app.py`) chỉ làm build lại các layer sau đó, không cài lại dependencies, nên build nhanh hơn nhiều.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định, bị thay thế khi truyền lệnh khác lúc `docker run image <lệnh>`. `ENTRYPOINT` là chương trình cố định luôn chạy; tham số của `docker run` (hoặc `CMD`) được nối thêm vào sau nó, muốn đổi phải dùng `--entrypoint`. Dockerfile này dùng `CMD ["python", "app.py"]` (dạng exec), nên `python` là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và run

Build từ **gốc repo** (Dockerfile `COPY` theo đường dẫn tính từ gốc):

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --name ex22-develop -p 18022:8000 my-agent:develop
$ curl -X POST "http://localhost:18022/ask?question=What%20is%20Docker%3F"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
[HTTP 200]
$ curl http://localhost:18022/health
{"status":"ok","uptime_seconds":3.4,"container":true}
[HTTP 200]
$ docker exec ex22-develop whoami
root
```

> Map ra cổng host `18022` vì cổng `8000` đang có container khác chạy. App develop nhận `question` qua query nên lệnh JSON trong `CODE_LAB.md` trả 422. Container chạy bằng **root**.

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`):** `python:3.11-slim` + cài `gcc`, `libpq-dev` để build package cần compile, rồi `pip install --user` vào `/root/.local`. Stage này không được deploy.
- **Stage 2 (`runtime`):** bắt đầu lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` (thư viện đã cài), `main.py`, `utils/`. Tạo user `appuser` và chạy bằng user đó (non-root), có `HEALTHCHECK`, chạy `uvicorn --workers 2`.
- **Tại sao nhỏ hơn:** (1) base `slim` thay cho bản `python:3.11` đầy đủ; (2) gcc, header, cache apt/pip chỉ nằm ở stage builder, không đi vào image cuối; (3) chỉ copy file cần để chạy.

Đo bằng `docker images` (Docker Desktop hiện cả dung lượng trên đĩa và dung lượng nén):

```text
$ docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   228405f277c0        240MB         57.4MB
my-agent:develop    e84411393417       1.67GB          426MB
```

| | Develop | Production | Giảm |
|---|---:|---:|---:|
| Disk usage | 1.67 GB (~1670 MB) | 240 MB | **~85.6%** |
| Content size (nén) | 426.3 MB | 57.4 MB | **~86.5%** |

`docker history` cho thấy phần app gần như bằng nhau (develop: layer `pip install` 53.3 MB; production: layer `COPY /root/.local` 40.8 MB). Khác biệt chủ yếu nằm ở base image `python:3.11` so với `python:3.11-slim`. Production còn chạy bằng `appuser` thay cho `root`.

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

Tạo `.env.local` rỗng (compose bắt buộc có file này) rồi chạy với `-p` riêng:

```text
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                            PORTS
agent     k5-day14-docker-agent   Up 3 seconds (health: starting)   8000/tcp
nginx     nginx:alpine            Up 3 seconds                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 14 seconds (healthy)           6333-6334/tcp
redis     redis:7-alpine          Up 14 seconds (healthy)           6379/tcp
```

**Architecture:**

```text
                      host :80 / :443
Client ──HTTP──▶  ┌──────────────┐
                  │    nginx     │  reverse proxy, rate limit 10 r/s (burst 20),
                  └──────┬───────┘  security headers
       network "internal" (bridge) │ proxy_pass http://agent:8000
                  ┌──────▼───────┐
                  │    agent     │  FastAPI, 2 uvicorn workers, không publish port
                  └──┬────────┬──┘
     REDIS_URL       │        │      QDRANT_URL
          ┌──────────▼─┐   ┌──▼──────────┐
          │ redis:6379 │   │ qdrant:6333 │
          └────────────┘   └─────────────┘
```

- **Services được start:** 4 (`agent`, `redis`, `qdrant`, `nginx`). `agent` chờ `redis` và `qdrant` healthy (`depends_on: condition: service_healthy`) mới start.
- **Cách giao tiếp:** tất cả chung network `internal`; gọi nhau bằng tên service qua DNS của Docker (`agent:8000`, `redis:6379`, `qdrant:6333`). Chỉ `nginx` mở port ra host, nên client không gọi thẳng agent được.

Test qua Nginx:

```text
$ curl http://localhost/health
{"status":"ok","uptime_seconds":1.4,"version":"2.0.0","timestamp":"2026-11-26T09:12:29.073194"}
[HTTP 200]

$ curl -i http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

**Nhận xét:**
- Response đi qua Nginx (header `Server: nginx` và các security header do Nginx thêm).
- `main.py` không dùng Redis hay Qdrant. Hai biến `REDIS_URL`, `QDRANT_URL` chỉ được truyền vào, nên mũi tên agent → redis/qdrant mới là kết nối dự kiến.
- `nginx` chỉ `depends_on: agent` mà không chờ healthy, nên lúc mới bật có một request `/health` bị lỗi `connect() failed (111: Connection refused)` vì agent chưa nghe cổng.

Dọn stack: `docker compose -p k5-day14-docker down -v`.

---

## Part 3: Cloud Deployment

_(Điền sau khi deploy agent Part 6 ở CP6.)_

---

## Part 4: API Security

### Exercise 4.1: API Key (`04-api-gateway/develop/app.py`)

- **Check ở đâu:** hàm `verify_api_key` (dòng 39–54) đọc header `X-API-Key` bằng `APIKeyHeader(name="X-API-Key", auto_error=False)`. Endpoint `/ask` gắn nó qua `Depends(verify_api_key)` (dòng 70), nên request bị chặn trước khi vào hàm xử lý.
- **Sai key thì sao:** thiếu key → **401** `Missing API key`; có key nhưng sai → **403** `Invalid API key.`
- **Rotate key:** key đọc từ env `AGENT_API_KEY`, nên đổi giá trị trên platform rồi restart/redeploy, không sửa code. Muốn không bị gián đoạn thì cho phép tạm thời cả key cũ và key mới (danh sách key), báo client chuyển sang key mới, rồi bỏ key cũ.
- **Điểm yếu thấy được:** nếu không đặt env thì app dùng key mặc định `demo-key-change-in-production`; khi chạy trực tiếp còn `print(f"API Key: {API_KEY}")` ra màn hình.

```text
$ AGENT_API_KEY=secret-key-123 python app.py

$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT (`04-api-gateway/production/`)

**Luồng JWT (`auth.py`):**
1. `POST /auth/token` với username/password. `authenticate_user` so với `DEMO_USERS`, sai thì trả 401.
2. `create_token` tạo payload `{sub, role, iat, exp = now + 60 phút}`, ký HS256 bằng `JWT_SECRET`.
3. Client gửi `Authorization: Bearer <token>`. `verify_token` kiểm chữ ký và hạn rồi lấy ra `username`, `role`, không cần tra DB mỗi request (stateless).
4. Không có token → 401; token hết hạn → 401; token sai chữ ký hoặc sai định dạng → 403.

> Endpoint và tài khoản thật là `POST /auth/token` với `student` / `demo123`, không phải `/token` với `admin` / `secret` như trong `CODE_LAB.md`. Token được che (`eyJ***REDACTED***`).

```text
$ curl -i http://localhost:8000/auth/token -X POST -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY

{"access_token":"eyJ***REDACTED***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer ***"}

# sai mật khẩu
{"detail":"Invalid credentials"}            [HTTP 401]

$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# token giả "abc.def.ghi"
{"detail":"Invalid token."}                 [HTTP 403]

$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK

{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Algorithm:** sliding window log. Mỗi user có một `deque` timestamp; mỗi request bỏ các timestamp cũ hơn 60 giây rồi đếm. Đủ giới hạn thì trả 429 kèm `Retry-After`, `X-RateLimit-*`.
- **Limit:** user thường **10 request/phút**; admin **100 request/phút**.
- **Bypass cho admin:** `app.py` chọn limiter theo role (`rate_limiter_admin if role == "admin"`). Admin không bị bỏ qua hẳn mà dùng giới hạn cao hơn (100/phút). Tài khoản `teacher` (role admin) gửi 15 request liên tiếp đều 200.

Vòng lặp 20 request với token `student` (request "Explain JWT" ở 4.2 đã tính là request thứ 1):

```text
Request  1: {...,"usage":{"requests_remaining":8,...}} [HTTP 200]
Request  2: {...,"usage":{"requests_remaining":7,...}} [HTTP 200]
...
Request  9: {...,"usage":{"requests_remaining":0,...}} [HTTP 200]
Request 10: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}} [HTTP 429]
Request 11: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}} [HTTP 429]
...
Request 20: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}} [HTTP 429]

$ curl -i ... (request tiếp theo)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795684448
retry-after: 59

# teacher (admin), 15 request
200 200 200 200 200 200 200 200 200 200 200 200 200 200 200
# student gọi /admin/stats
{"detail":"Admin only"}                     [HTTP 403]
```

→ Bị chặn đúng ở request thứ **11** trong 60 giây. Hạn chế: state nằm trong RAM của process, nên mỗi instance hay worker đếm riêng và restart là mất. Part 6 chuyển sang Redis để mọi instance dùng chung.

### Exercise 4.4: Cost guard

**Cách làm:** trước khi gọi LLM, ước lượng chi phí rồi cộng vào bộ đếm chi tiêu **theo user, theo tháng** trong Redis (`budget:<user_id>:<YYYY-MM>`). Nếu tổng mới vượt **$10** thì hoàn lại phần vừa cộng và từ chối (API trả **402 Payment Required**).

- Dùng `INCRBYFLOAT` (một lệnh nguyên tử): cộng trước rồi mới so. Như vậy 2 instance gọi cùng lúc không thể cùng đọc thấy "còn tiền" rồi cùng vượt budget. Lời giải mẫu đọc (`GET`) rồi mới ghi (`INCRBYFLOAT`) nên có race condition này.
- Reset đầu tháng: key chứa tháng (`2026-11`), sang tháng mới thì dùng key mới; `EXPIRE` 32 ngày để key cũ tự xoá.
- Tháng tính theo UTC để mọi instance (có thể ở múi giờ khác nhau) dùng chung một key.

```python
from datetime import datetime, timezone
import redis

r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
MONTHLY_BUDGET_USD = 10.0

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"

    new_total = r.incrbyfloat(key, estimated_cost)   # nguyên tử
    if new_total > MONTHLY_BUDGET_USD:
        r.incrbyfloat(key, -estimated_cost)          # hoàn lại
        return False

    r.expire(key, 32 * 24 * 3600)
    return True
```

Chạy thử với Redis thật (`redis:7-alpine`):

```text
call 1: estimated $3.00 -> True, spent = $3.00
call 2: estimated $3.00 -> True, spent = $6.00
call 3: estimated $3.00 -> True, spent = $9.00
call 4: estimated $3.00 -> False, spent = $9.00
call 5: estimated $3.00 -> False, spent = $9.00
small call $0.50 -> True
bob (user khac) $3.00 -> True
TTL key alice (giay): 2764800
```

**So với `04-api-gateway/production/cost_guard.py`:** bản mẫu giữ usage trong dict (RAM), budget $1/ngày mỗi user và $10/ngày toàn hệ thống (vượt toàn hệ thống trả 503). Có một lỗi: response `/ask` ghi `"budget_remaining_usd": usage.total_cost_usd`, tức là **số đã tiêu** chứ không phải số còn lại. Ở trên, `/ask` trả `budget_remaining_usd: 0.000179`, còn `/me/usage` trả `budget_remaining_usd: 0.999821`.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

- `/health` (**liveness**): process còn sống là 200; kèm uptime, version và kiểm tra RAM bằng `psutil` (`degraded` nếu RAM > 90%). Platform dùng nó để quyết định **restart** container.
- `/ready` (**readiness**): 503 khi đang khởi động, đang tắt hoặc chưa kết nối được dependency. Load balancer dùng nó để quyết định **có gửi traffic** vào instance hay không.
- Tách hai endpoint vì Redis/DB chết thì không nên restart app (restart cũng không chữa được), chỉ nên ngừng nhận traffic.

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":2.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T09:13:41.636412+00:00","checks":{"memory":{"status":"ok","used_percent":22.9}}}
[HTTP 200]
$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
[HTTP 200]
```

(`in_flight_requests` = 1 vì middleware đếm luôn chính request `/ready`.)

### Exercise 5.2: Graceful shutdown

Gửi request rồi `kill -TERM` ngay sau đó (~30 ms):

```text
$ python app.py &
$ curl -X POST "http://localhost:8000/ask?question=Long%20task" &
$ kill -TERM 7
Kết quả request đang chạy: {"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."} [HTTP 200]
Exit code của app: 0
$ curl http://localhost:8000/health   (sau khi tắt)
[HTTP 000]   ← không còn nhận kết nối
```

Log của app:

```text
INFO:     Shutting down
INFO:     127.0.0.1:60462 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 09:13:44,814 INFO 🔄 Graceful shutdown initiated...
2026-11-26 09:13:44,814 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [7]
2026-11-26 09:13:44,814 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Giải thích:** uvicorn nhận SIGTERM → ngừng nhận kết nối mới (`Shutting down`) → chờ request đang chạy xong (request trả 200 *sau* dòng `Shutting down`) → chạy phần sau `yield` của lifespan → thoát với exit code 0. `timeout_graceful_shutdown=30` giới hạn thời gian chờ. Handler `handle_sigterm` tự viết chỉ chạy **sau cùng**, vì uvicorn giữ tín hiệu trong lúc chạy rồi trả lại cho handler cũ khi đã tắt xong. Nếu handler tự viết mà thay mất handler của uvicorn và không gọi lại nó, process sẽ không bao giờ tắt.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

- State (lịch sử hội thoại) không giữ trong biến Python mà lưu trong Redis: `session:<session_id>` → JSON `{"history": [...]}`, ghi bằng `SETEX` với TTL 3600 giây, giữ tối đa 20 message.
- Mỗi request `/chat` đọc session từ Redis, thêm câu hỏi và câu trả lời rồi ghi lại, nên **bất kỳ instance nào** cũng phục vụ tiếp được cuộc hội thoại.
- Tại sao cần: chạy nhiều instance thì mỗi instance có RAM riêng. Nếu lưu `conversation_history = {}` trong RAM, request 2 rơi vào instance khác sẽ không thấy lịch sử; instance restart hay bị scale down cũng mất hết.
- **Rủi ro còn lại trong code mẫu:** nếu lúc import không ping được Redis, app lặng lẽ chuyển sang `_memory_store` (in-memory) và trở lại có state, dù `/ready` vẫn 200 vì `USE_REDIS=False`. Production nên để `/ready` trả 503 thay vì tự chuyển sang lưu trong RAM.

### Exercise 5.4: Load balancing (3 instance + Nginx)

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 15 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 14 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 26 seconds (healthy)   6379/tcp
```

10 request `POST /chat` qua `http://localhost:8080`:

```text
Request 1 -> instance-7da8de | storage: redis
Request 2 -> instance-565138 | storage: redis
Request 3 -> instance-7da8de | storage: redis
Request 4 -> instance-67d024 | storage: redis
Request 5 -> instance-565138 | storage: redis
Request 6 -> instance-7da8de | storage: redis
Request 7 -> instance-67d024 | storage: redis
Request 8 -> instance-565138 | storage: redis
Request 9 -> instance-7da8de | storage: redis
Request 10 -> instance-67d024 | storage: redis

$ docker compose -p k5-day14-scaling logs agent | grep "POST /chat" (đếm theo container)
      3 agent-1
      3 agent-2
      4 agent-3
```

**Giải thích:** Nginx `proxy_pass http://agent:8000`; DNS của Docker trả về IP của cả 3 container `agent`, nên traffic được chia vòng tròn (3/3/4). `proxy_next_upstream error timeout http_503` cho phép thử instance khác khi một instance lỗi.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: 1fd6fc41-e803-4f39-9f77-b8f67ee4d091

Request 1: [instance-565138]   Q: What is Docker?
Request 2: [instance-7da8de]   Q: Why do we need containers?
Request 3: [instance-67d024]   Q: What is Kubernetes?
Request 4: [instance-565138]   Q: How does load balancing work?
Request 5: [instance-7da8de]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-7da8de', 'instance-67d024', 'instance-565138'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu hỏi của cùng một session được 3 instance khác nhau trả lời, nhưng history vẫn đủ 10 message (5 user + 5 assistant), vì mọi instance đọc và ghi chung một key trong Redis.

**Thử thêm (script không tự tắt instance):** tạo một session 5 lượt bằng `test_stateless.py`, rồi tắt một instance và hỏi tiếp cùng session đó:

```text
$ docker stop k5-day14-scaling-agent-2
turn 7 -> instance-565138 [HTTP 200]
turn 8 -> instance-7da8de [HTTP 200]
turn 9 -> instance-565138 [HTTP 200]
turn 10 -> instance-7da8de [HTTP 200]
$ curl http://localhost:8080/chat/<session_id>/history
count = 18
```

→ Mất 1 instance thì Nginx chuyển traffic sang 2 instance còn lại, không có request lỗi, lịch sử vẫn đủ 18 message (9 lượt). (Số `turn` hiển thị lệch +1 so với lượt thật vì code đếm history *sau khi* đã thêm câu hỏi hiện tại rồi lại `+ 1`.)

Dọn stack: `docker compose -p k5-day14-scaling down`.

---

## Part 6: Final Project — output `check_production_ready.py`

Chạy bản đầy đủ (có Docker) trong `06-lab-complete/`:

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

---

## AI log

| Phần | Hỏi AI gì | Nhận được gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|
| Part 6 (code) | Dùng Claude Code viết các TODO trong `06-lab-complete/` (config, auth, rate limiter Redis, cost guard Redis, `/health`, `/ready`, log JSON, Dockerfile multi-stage, compose, deploy config) | Code cho 12 file | Chạy `check_production_ready.py` bản đầy đủ: PASS 12/12. Thử thêm bằng `docker compose up`: 401 khi thiếu key, 422 khi câu hỏi rỗng, 429 sau 10 request kèm `Retry-After`, tắt Redis thì `/health` 200 còn `/ready` 503. Phát hiện và sửa lỗi compose không nhận `AGENT_API_KEY` từ biến shell |
| Part 2 | Hỏi vì sao `docker build` báo `GetFileAttributesEx 02-docker: The system cannot find the file specified` | Phải build từ gốc repo vì Dockerfile `COPY` theo đường dẫn tính từ gốc | Chạy lại từ gốc repo, build thành công |
| Part 2 | Hỏi vì sao `curl` JSON vào `/ask` trả 422 `loc: ["query","question"]` | App develop nhận `question` qua query string | Gọi `?question=...` → 200 |
| Part 7 | Dùng Claude Code chạy load test, eval, stack Prometheus/Grafana/Jaeger/Locust, thí nghiệm alert, chụp ảnh và soạn `BENCHMARK_REPORT.md`; thêm 2 entry `KNOWLEDGE_BASE`, metric `agent_question_length_chars`, job CI `.github/workflows/eval.yml` | Lệnh, file JSON/CSV, ảnh, bản nháp báo cáo | Mọi số trong báo cáo lấy từ `reports/*.json`, `benchmark-results/*.csv` và API Prometheus/Jaeger. Eval cuối 23/23 không regression. Chạy thử job CI: v2 exit 0, v1 exit 1. Phát hiện và sửa: Dockerfile production thiếu `PYTHONUSERBASE` (agent không khởi động được); lệnh `compose run locust` tự đưa agent về 2 replica nên chạy lại benchmark scale với `--no-deps` |
