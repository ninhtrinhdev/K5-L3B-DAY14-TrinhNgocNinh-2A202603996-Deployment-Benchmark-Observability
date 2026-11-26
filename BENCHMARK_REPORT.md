# Benchmark & Observability Report — Day 14

**Họ tên:** Trịnh Ngọc Ninh — 2A202603996
**Ngày chạy:** 26/11/2026
**Môi trường:** Windows 11, Docker Desktop 29.5.2 (12 CPU, 3.5 GB RAM cho Docker). Bước 1 chạy trong container `python:3.11-slim` (máy chỉ có Python 3.14), agent v1 ở cổng 8001, v2 ở 8002, `load_test.py` và `run_eval.py` chạy cùng container đó. Bước 2 chạy bằng Docker Compose (`-p k5-day14-observability`), mỗi agent giới hạn `cpus: 0.5`, `memory: 256M`.

File số liệu: `reports/*.json` (Bước 1), `benchmark-results/scale_*_stats.csv` (Bước 2), ảnh trong `screenshots/`.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | LLM mock mất ~150–220 ms cho phần lớn request (p50 ≈ 190 ms), nên 500 ms còn dư gấp ~2 lần cho mạng và tải. Đặt theo p95 chứ không theo avg để nhóm request chậm không bị che đi. Alert dùng ngưỡng lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn |
| Error rate `/ask` | < 2 % | Mock LLM có ~1 % lỗi upstream ngẫu nhiên (`MOCK_ERROR_RATE=0.01`). 2 % cho phép mức nền đó mà vẫn bắt được sự cố thật; alert đặt ở 5 % trong 1 phút |
| Accuracy trên golden dataset | ≥ 85 % (gate CI), mục tiêu 100 % | v2 ban đầu 91.3 %, sau khi sửa KB đạt 100 %. Gate 85 % trong CI cộng thêm điều kiện **không có câu bị regression** so với baseline |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.28 | 192.2 | 218.5 | 1691.8 | 1.67 % | ✅ PASS |
| 10 | 40.62 | 190.9 | 221.8 | 1688.0 | 0.00 % | ✅ PASS |
| 50 | 98.54 | 208.6 | 424.4 | 1732.1 | 0.33 % | ✅ PASS |
| 100 | 42.69 | 873.9 | 4540.1 | 5095.8 | 1.00 % | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS tăng gần tuyến tính từ 1 → 10 (4.28 → 40.62, ×9.5) vì mỗi request chủ yếu là *chờ* LLM (`asyncio.sleep`), một process async phục vụ song song được nhiều request mà latency không đổi (p50 ~190 ms). Từ 10 → 50 chỉ tăng ×2.4 (98.5 req/s) và p95 bắt đầu tăng (424 ms): CPU của một process uvicorn (và cả `load_test.py` chạy cùng container) bắt đầu thành nút thắt. Ở 100, hệ thống **quá tải**: RPS *giảm* còn 42.7, p50 lên 874 ms, p95 4.5 s. Request phải xếp hàng chờ event loop, nên thêm concurrency chỉ làm tăng độ dài hàng đợi chứ không tăng throughput. Theo Little's Law (`RPS ≈ concurrency / latency`), latency tăng nhanh hơn concurrency nên RPS giảm.

### 2.2 Tail latency (concurrency 20, 300 request)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 190.3 | 222.9 | 247.3 |
| 0.03 (mặc định) | 252.9 | 237.7 | 1703.1 |
| 0.1 | 358.2 | 1696.4 | 1716.4 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Chỉ số nhạy nhất với request chậm là **percentile đuôi**. Với 3 % request chậm, avg chỉ tăng 63 ms (190 → 253) và p95 gần như không đổi, nhưng p99 nhảy từ 247 ms lên 1703 ms. Với 10 % (vượt quá 5 %), cả p95 cũng lên 1696 ms (gấp 7.6 lần), trong khi avg mới tăng 168 ms. Average trộn nhóm nhanh với nhóm chậm nên che giấu việc cứ 10 người thì 1 người chờ gần 2 giây. SLO theo avg (vd < 500 ms) vẫn "PASS" ở cả 3 cấu hình dù trải nghiệm của nhóm chậm rất tệ. SLO theo p95/p99 thì bắt được: lần chạy 0.1 bị `load_test.py` báo FAIL (exit code 1).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 57.2 | 108.8 | 117.6 |
| Tổng cost (USD) | 0.000405 | 0.000757 | 0.000824 |
| Cost / câu đúng (USD) | 0.00040515 | 0.00003607 | 0.00003583 |
| Latency p50 / p95 (ms) | 153.5 / 180.8 | 180.1 / 214.0 | 182.2 / 212.2 |
| Quality gate | FAIL (accuracy < 80 %) | PASS (≥ 80 %, 0 regression) | PASS (≥ 100 %, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Lệnh cuối: `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json` → `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`, exit code 0.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Retrieval không khớp tài liệu nào nên v2 trả câu chung chung. Thêm vào `KNOWLEDGE_BASE` một tài liệu với từ khoá `["jwt", "json web token"]`, nội dung nói JWT là token có thời điểm hết hạn (exp), được ký, server kiểm chữ ký thay vì tra DB, so với API key cố định |
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm tài liệu với từ khoá `["hpa", "horizontal pod autoscaler", "kubernetes"]`: HPA scale theo CPU, memory hoặc custom metrics |

Trước khi thêm, đã kiểm tra `jwt`, `kubernetes`, `hpa` chỉ xuất hiện trong đúng 2 câu này của golden dataset, nên không có câu nào khác bị đổi tài liệu (0 regression). Không sửa `golden_dataset.jsonl`. Phần sửa được chép sang `production/utils/mock_llm.py` để stack Docker cũng trả lời đúng.

**Quality gate trong CI:** `.github/workflows/eval.yml` chạy trên mọi PR và push vào `main`. Job bật agent v2 (`MOCK_ERROR_RATE=0` để đo chất lượng, không đo lỗi ngẫu nhiên), rồi chạy `run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`. `run_eval.py` trả **exit code 1** khi accuracy < ngưỡng hoặc có câu bị regression, nên step fail, job đỏ, và branch protection chặn merge. Đã chạy thử đúng các bước của job: v2 → `✅ PASS`, exit 0; trỏ sang v1 → `❌ FAIL`, exit 1 (20 câu regression).

**Trade-off v1 ↔ v2:** v2 có thêm bước retrieval nên prompt dài hơn: tokens/câu ×1.9 (57 → 109), tổng cost ×1.9, p95 latency +33 ms (181 → 214 ms, gồm ~20 ms retrieval và thời gian xử lý thêm token). Đổi lại accuracy từ 4 % lên 91 % (rồi 100 %). Tính theo **cost / câu đúng** thì v2 rẻ hơn **~11 lần** ($0.000036 so với $0.000405). Tức là trả thêm ~2 lần tiền mỗi câu nhưng gần như mọi câu đều dùng được. So hai phiên bản bằng cost/câu thì v1 có vẻ rẻ, còn cost/câu đúng mới phản ánh chi phí cho một câu trả lời có giá trị.

---

## 4. Observability stack (production)

### 4.0 Exercise 7.1 và 7.4

**7.1. Ví dụ từng loại metric (`curl localhost:8002/metrics`):**
- Counter: `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total{model="mock-llm-small",type="input"} 91.0`
- Gauge: `agent_in_flight_requests 0.0`, `agent_info{model="mock-llm-small",version="v2"} 1.0`
- Histogram: `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0` (+ `_sum`, `_count`)
- Đã thêm `agent_question_length_chars` (Histogram, bucket 20…2000 ký tự, **không** có label): `agent_question_length_chars_count 1.0`, `_sum 40.0`.

**Nếu label `route` dùng URL thật:** mỗi URL lạ mà bot quét (`/wp-admin`, `/.env`, `/a1b2c3`…) sinh ra một time series mới cho cả counter lẫn 11 bucket của histogram. Hàng nghìn URL thành hàng chục nghìn series (cardinality bùng nổ), Prometheus tốn RAM, query chậm, có thể sập. Dùng route template (`/ask`) và gom phần còn lại thành `unmatched` thì số series cố định.

**7.4 (stack 2 agent, Locust 30 user, đọc lúc 16:41):**

| Câu hỏi | Trả lời (số từ Prometheus / dashboard) |
|---|---|
| p95 và avg bao nhiêu? | p95 **293.76 ms** (panel Latency p95), avg **231 ms**, p50 176 ms, nhưng p99 **1815 ms**. p95 và avg gần nhau (cách ~63 ms) vì chỉ ~3 % request chậm, dưới ngưỡng 5 %. Khoảng cách thật nằm giữa avg và **p99**: ~1 % người dùng chờ gần 2 s, avg không cho thấy điều đó |
| Nginx có chia đều cho 2 instance? | Có: 9.49 req/s và 9.31 req/s (panel "Requests/s theo instance"), lệch ~2 %, đúng kiểu round-robin |
| Vì sao input tokens/s > output tokens/s? | 1473 so với 784 tokens/s. Input = system prompt + **tài liệu retrieve được (context RAG)** + câu hỏi, còn output chỉ là câu trả lời ngắn. v2 thêm context nên input gần gấp đôi output (khi đổi sang v1 ở thí nghiệm E, input giảm còn 681 tokens/s) |
| `curl http://localhost:8080/metrics` trả gì? | **404 Not Found** từ Nginx. `nginx.conf` có `location = /metrics { return 404; }`: metric lộ thông tin nội bộ (route, lưu lượng, version, chi phí) nên không public ra internet. Prometheus vẫn scrape được vì nó gọi thẳng từng container `agent:8000` trong mạng nội bộ Docker (DNS service discovery), không đi qua Nginx |

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png` (19.0 req/s, error rate 0.96 %, p95 293.76 ms, in-flight 3, 2 instance)
- [x] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với 2 alert cùng **firing** (`AgentHighErrorRate` + `AgentInstanceDown`): `screenshots/prometheus-alert-firing.png`

Unit test alert: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống" (Locust 30 user chạy suốt)

Thời gian đo bằng script đọc `GET /api/v1/alerts` của Prometheus mỗi 2 s, tính từ lúc `docker compose up -d agent` (đổi env) xong.

| # | Thay đổi | Alert nào firing | Thời gian đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending 27 s → **firing 87 s** | Error rate: 18.8 % lúc firing (21.8 % khi alert đã active 2 phút, xem ảnh), vượt ngưỡng 5 %; p95 không đổi (0.292 s) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | pending 31 s → **firing 151 s** | Latency p50/p95/p99: p95 1.908 s, p99 1.982 s, trong khi p50 0.206 s và avg 0.597 s |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | pending 31 s → **firing 151 s** | Cost burn rate: $1.63/giờ → **$17.28/giờ** (×10.6); latency cũng tăng (p95 /ask 0.73 s, avg 0.505 s) vì model large chậm hơn 2.5 lần |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` | pending 10 s → **firing 41 s** | Instances up 2 → 1; Requests/s theo instance (instance còn lại gánh ~11.7 req/s) |
| E | `AGENT_VERSION=v1` | **Không có** (theo dõi 150 s) | — | Retrieval hit ratio mất dữ liệu (v1 không gọi retrieval), tokens/s giảm (input 1261 → 681), bảng version đổi sang v1; error rate 0.49 %, p95 246 ms vẫn xanh |

Ghi chú:
- Thời gian firing ≈ thời gian để rate trong cửa sổ `[1m]` vượt ngưỡng (pending) + `for` của rule (1 m, 2 m, 2 m, 30 s).
- D làm **cùng lúc** với A để chụp 2 alert firing. Trong ~1.5 phút pause, Nginx ghi **31 response 504** (agent treo quá `proxy_read_timeout 10s`), nhưng metric của agent chỉ có status 200 và 503, **không có 504**: request không bao giờ được agent xử lý xong nên agent không đếm. Phải giám sát thêm ở tầng load balancer hoặc dùng synthetic check từ bên ngoài. Dùng `pause` (không dùng `stop`) vì container bị pause vẫn còn trong Docker DNS nên Prometheus thấy `up == 0`; container bị stop biến mất khỏi DNS, Prometheus coi như target không tồn tại và không có alert.
- Sau C, đổi về model small thì `LLMCostBurnRateHigh` vẫn firing thêm ~5 phút (hết lúc 16:58:09, đổi lúc 16:53:06), vì rule dùng `rate(...[5m])`: dữ liệu của model large còn nằm trong cửa sổ. Cửa sổ dài giúp ổn định nhưng làm alert chậm "tự hết".

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**

Metric hạ tầng (latency, error, traffic, saturation) chỉ cho biết agent *trả lời được*, không cho biết trả lời *đúng*. v1 còn nhanh hơn và rẻ hơn nên dashboard trông "tốt hơn". Cần thêm:
1. **Eval trong CI/CD** (đã làm, `.github/workflows/eval.yml`): chạy golden dataset trước mỗi deploy và chặn bản bị regression. Đổi sang v1 thì gate fail ngay (exit code 1, 20 câu regression).
2. **Giám sát chất lượng khi chạy thật:** chạy eval định kỳ (synthetic) trên production, lấy mẫu câu trả lời để LLM-as-judge chấm, thu thập feedback người dùng (👍/👎); đưa các chỉ số đó thành metric và alert.
3. **Metric gián tiếp:** retrieval hit ratio (rớt về 0 ở E), avg input tokens/câu, `agent_info{version}`, kèm alert khi version hoặc hit ratio thay đổi bất thường.

### 4.3 Debug bằng trace

Chọn trace chậm nhất trong 1 giờ (106 trace `/ask` ≥ 1 s):

- `trace_id`: `9f3aa3db27e86a2d93253edb86d414da`
- Tổng thời gian: **8206.8 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (7979.3 ms, **97.2 %**). `agent.run` 8004.2 ms, `agent.retrieve_context` chỉ 24.7 ms (0.3 %). Input 82 token, output 44 token.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent --no-log-prefix | grep 9f3aa3db27e86a2d93253edb86d414da`):

```json
{"ts": "2026-11-26T09:42:29.180938+00:00", "level": "INFO", "service": "observable-agent", "instance": "287a608e96e1", "event": "llm_call", "trace_id": "9f3aa3db27e86a2d93253edb86d414da", "span_id": "e2470e7a8bee4d39", "request_id": "963c70b18ce9", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 82, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1637.5}
{"ts": "2026-11-26T09:42:29.183238+00:00", "level": "INFO", "service": "observable-agent", "instance": "287a608e96e1", "event": "http_request", "trace_id": "9f3aa3db27e86a2d93253edb86d414da", "span_id": "e2470e7a8bee4d39", "request_id": "963c70b18ce9", "method": "POST", "route": "/ask", "status": 200, "ms": 8009.2}
```

**Phân tích:** bước chậm là gọi LLM chứ không phải retrieval hay code của agent. Log cho thấy mock LLM tự định latency **1637.5 ms** (đây là một request "slow" của `MOCK_SLOW_RATE`), nhưng span đo được **7979 ms**. Phần chênh ~6.3 s là thời gian *chờ CPU*: mỗi agent bị giới hạn `cpus: 0.5`, khi event loop bận thì `asyncio.sleep` xong muộn hơn nhiều so với thời gian đặt. Trace đo thời gian thực mà người dùng phải chờ, nên bắt được cả độ trễ do saturation mà con số tự báo của LLM không thấy. Trong toàn bộ 3684 `llm_call` lúc đó, 101 cái có `llm_ms` > 1 s, lớn nhất 1696.5 ms, nên các trace vài giây là do hàng đợi CPU.

Trace lỗi: `149344543e0c3981627380c3bc785e00` (99.8 ms, HTTP 503). Span `chat mock-llm-small` có `error.type=upstream_unavailable` và event `exception` (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`, kèm stacktrace). Log cùng `trace_id`:

```json
{"ts": "2026-11-26T09:42:42.865563+00:00", "level": "INFO", "service": "observable-agent", "instance": "287a608e96e1", "event": "llm_error", "trace_id": "149344543e0c3981627380c3bc785e00", "span_id": "9c152e4808c8f683", "request_id": "296626b47fc8", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS (`/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.46 | 200 | 360 | 1700 | 67 / 7044 (0.95 %) |
| 3 | 59.34 | 190 | 290 | 1700 | 69 / 7088 (0.97 %) |

Nguồn: `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv` (dòng `/ask`). Tổng cả `/health`: 65.48 và 65.63 req/s. Failures đều là 503 từ lỗi upstream giả lập (~1 %).

> Lệnh trong CP8 (`docker compose run --rm locust ...`) **tự khởi động lại** các service phụ thuộc (locust → nginx → agent) và đưa agent về `deploy.replicas: 2`. Lần chạy "1 instance" đầu tiên vì vậy thực ra có 2 instance (Prometheus thấy 2 target ~30 req/s mỗi cái). Kết quả trên được chạy lại với `run --rm --no-deps`, đã kiểm tra `instances up = 1` (một instance nhận 61 req/s) và `= 3` (20 req/s mỗi instance).

**Giải thích:** scale từ 1 lên 3 **không tăng RPS** (59.5 so với 59.3) và chỉ cải thiện p95 một chút (360 → 290 ms); p50 và p99 gần như không đổi.
- **RPS do phía tạo tải quyết định:** Locust là mô hình *đóng*, mỗi user hỏi rồi nghỉ 0.5–2 s, nên 100 user tạo khoảng 100 / (1.25 s + 0.25 s) ≈ 60–65 req/s dù server mạnh tới đâu. Một instance đã xử lý hết 60 req/s, nên thêm instance không có thêm việc để làm.
- **Latency có mức sàn ở LLM:** panel LLM latency cho p95 ≈ 198 ms, mỗi request phải chờ LLM ~150–220 ms (và ~1.7 s với 3 % request chậm, nên p99 = 1700 ms ở cả hai). Scale ngang không làm LLM nhanh hơn, nên **nút thắt là LLM upstream**.
- p95 giảm nhẹ vì với 1 instance (0.5 CPU) đã có chút xếp hàng CPU (in-flight lên ~8); chia cho 3 instance thì mỗi instance chỉ 20 req/s, hàng đợi ngắn hơn. Scale chỉ đáng giá khi CPU hoặc hàng đợi của agent là nút thắt; muốn giảm latency thật thì phải xử lý LLM (model nhanh hơn, cache, streaming).

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối, percentile thì không.** Cùng một hệ thống mà avg chỉ +63 ms trong khi p99 ×7. SLO và alert phải theo p95/p99, và phải đọc thêm p99/max để thấy tail.
  2. **Metric hạ tầng xanh không có nghĩa là agent đúng.** Đổi sang v1 làm accuracy từ 100 % xuống 4 % mà không alert nào kêu. Chất lượng phải được đo riêng bằng eval có baseline và gate bằng exit code trong CI.
  3. **Mỗi tầng chỉ thấy những gì nó xử lý, và benchmark phải tự kiểm chứng.** Agent không thấy 504 của Nginx; span 8 s trong khi LLM chỉ 1.6 s (chờ CPU); lệnh `compose run` âm thầm scale lại thành 2 instance. Chỉ đối chiếu chéo metrics, traces, logs (cùng `trace_id`) và kiểm tra lại số instance thật mới thấy được những chỗ này.
- Nếu đưa agent này lên production thật, sẽ thêm:
  - Metric và alert ở **Nginx** (tỉ lệ 5xx, 504, upstream response time) và **synthetic check** từ bên ngoài.
  - **Alert theo SLO burn rate** (multi-window, vd 1 h + 5 m) thay cho ngưỡng cố định, để vừa nhanh vừa ít báo động giả.
  - **CPU throttling / saturation** của container (`container_cpu_cfs_throttled_seconds_total`) và độ dài hàng đợi, vì trace cho thấy chờ CPU có thể làm request chậm gấp 5 lần.
  - **Chất lượng:** eval định kỳ trên production, retrieval hit ratio, tỉ lệ câu trả lời "chung chung"; alert khi hit ratio hoặc `agent_info{version}` đổi bất thường.
  - **Cost:** alert ngân sách theo ngày/tháng (đã làm cost guard ở Part 6) và cost theo từng tenant ở log, không đặt làm label.
