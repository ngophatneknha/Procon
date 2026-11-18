# Procon Việt Nam 2026 — HEXUDON: bộ giải tối ưu lộ trình

Bộ mô phỏng chính xác theo luật, bộ kiểm tra hợp lệ, bộ giải (heuristic + metaheuristic) và client
kết nối server thi đấu chính thức cho bài toán **HEXUDON** (thể thức KOSEN, bản đồ lục giác).

Kết quả chạy thật trên server Practice (đề câu 1, 5 xe): **F1 = 32/32 chuỗi, F2 = 288, F3 = 332**,
khớp chính xác với mô phỏng nội bộ (chi tiết: [docs/RESULTS.md](docs/RESULTS.md), log: [logs/](logs/)).

## Cấu trúc

```
hexudon/            thư viện chính
  models.py           kiểu dữ liệu (MapConfig, Action, DayInput, ...)
  engine.py           HexGrid (even-r, Dijkstra) + HexudonEngine (mô phỏng từng bước, kiểm tra hợp lệ)
  cpp_accel.cpp       lõi C++ tính APSP;  fast_apsp.py nạp hexudon_fast.dll (có fallback Python)
  heuristics.py       các heuristic H1–H7
  solver.py           HexudonSolver: chọn vai trò xe, lập kế hoạch từng ngày (rollout, 2-opt, ILS, beam, ES)
  protocol.py         chuyển đổi định dạng JSON chính thức (schema.pdf) <-> mô hình nội bộ
  client.py           MatchRunner (chạy trận cục bộ) và ContestApiClient (gọi API server)
  arena.py            đấu trường nhiều đội cục bộ;  generator.py  sinh bản đồ ngẫu nhiên
run_online.py       chơi một trận thật/practice trên server
run_benchmark.py    benchmark cục bộ + giải đấu 4 đội;  build_visualizer.py -> visualizer.html
experiments/        script thí nghiệm (bench_wide, exp_roles, exp_gap, real_bench, real_roles)
tests/              kiểm thử tự động
docs/               ALGORITHMS.md (thuật toán, công thức), RESULTS.md (thí nghiệm),
                    PLATFORM_NOTES.md (API/định dạng chính thức), Problem_VI.pdf (đề bài)
logs/               log chạy thật và mô phỏng Q1–Q5
```

## Chạy

Yêu cầu: Python 3.10+, không cần thư viện ngoài. Chạy từ thư mục gốc của repo.

```powershell
python -m unittest discover -s tests          # 13 test, ~1 phút
python run_benchmark.py                       # benchmark cục bộ
python build_visualizer.py                    # tạo visualizer.html từ sample_replays.json
```

Trận trên server (token lấy từ website, chỉ truyền qua biến môi trường, không lưu vào file):

```powershell
$env:HEXUDON_TOKEN = "<JWT>"
python run_online.py --base-url https://hexudon.hairbui76.id.vn --game-id <game_id> --practice
python run_online.py --base-url https://hexudon.hairbui76.id.vn --game-id <game_id> --practice --dry   # chỉ lập kế hoạch, không gửi
```

Kết quả: `GET /api/game/result?game_id=<game_id>:<team_id>` →
`distinct_types` (F1), `cumulative_daily_types` (F2), `total_servings` (F3), `cumulative_response_time` (F4).

Thí nghiệm (xem tham số trong [docs/ALGORITHMS.md](docs/ALGORITHMS.md)):

```powershell
python experiments/bench_wide.py 12 120       # 12 map ngẫu nhiên, ngân sách 120 ms/ngày
python experiments/real_bench.py 1 800        # mô phỏng trên bản đồ thật (cần thư mục ref/, không đưa vào repo)
```

Biên dịch lại lõi C++ (tùy chọn, cần g++): `g++ -O3 -march=native -std=c++20 -shared -static -o hexudon/hexudon_fast.dll hexudon/cpp_accel.cpp`

## Hạn chế đã biết
- Mới chạy thật trên 1 trong 5 đề Practice; chưa thử chế độ Active.
- F3 (số phần) còn dao động theo ngày; chưa so sánh được với đội khác.
- `hexudon_fast.dll` là bản build cho Windows x64; trên hệ khác cần biên dịch lại hoặc dùng fallback Python (chậm hơn).
