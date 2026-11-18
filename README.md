# Procon Việt Nam 2026 — Tối Ưu Hoá Lộ Trình HEXUDON

Hệ thống mô phỏng (Simulator), kiểm định hợp lệ (Validator), lõi tăng tốc C++20 (`hexudon_fast.dll`), bộ giải 7 Heuristic + Metaheuristics (H1–H7, 2-Opt, Regret-2 Auction, Via-Spot Detour, 1-Day Lookahead Rollout), đấu trường đối kháng 4 đội (`MultiTeamArena`) và công cụ trực quan hóa ([visualizer.html](file:///E:/procon/visualizer.html)) cho bài toán **HEXUDON — Procon Việt Nam 2026**.

**Tài liệu:** [ALGORITHMS.md](ALGORITHMS.md) — mô tả chi tiết từng thuật toán · [RESULTS.md](RESULTS.md) — kết quả thí nghiệm · [HEXUDON_MASTER_HANDOFF.md](HEXUDON_MASTER_HANDOFF.md) — luật và kiến trúc.

## 1. Cấu trúc Thư mục

- [hexudon/models.py](file:///E:/procon/hexudon/models.py): Định nghĩa cấu trúc dữ liệu chuẩn (`MapConfig`, `TerrainType`, `RoadState`, `Spot`, `AgentRole`, `Action`, `DayInput`, `DayResult`, `MatchScore`).
- [hexudon/engine.py](file:///E:/procon/hexudon/engine.py):
  - `HexGrid`: Hệ tọa độ lục giác đỉnh nhọn `even-r` (hàng chẵn lệch phải 0.5 ô theo Hình 1 trong đề), khoảng cách lục giác và Dijkstra đa tiêu chí.
  - `HexudonEngine`: Bộ mô phỏng chính xác từng bước (step-by-step), cập nhật giao thông đường bộ 2 ngày gần nhất, tự động nạp xăng khi đứng chung ô $\ge 1$ bước, và **Action Validator** ngăn chặn tuyệt đối mọi lệnh `Invalid`.
- [hexudon/cpp_accel.cpp](file:///E:/procon/hexudon/cpp_accel.cpp) & [hexudon/fast_apsp.py](file:///E:/procon/hexudon/fast_apsp.py):
  - Lõi C++20 biên dịch thành `hexudon_fast.dll` (`g++ -O3 -march=native`), tính toán APSP với **Spot-Collecting Tie-Breaker** (khi hai đường đi có cùng số bước và nhiên liệu, tự động chọn nhánh đi ngang qua nhiều quán Udon nhất).
- [hexudon/heuristics.py](file:///E:/procon/hexudon/heuristics.py):
  - **H1**: Độ hiếm Chuỗi & Độ cô lập góc biên (`chain_scarcity`, `spot_isolation`).
  - **H2**: Trường thế năng cụm điểm đến (`compute_gravity_potential`).
  - **H3**: Đốt xăng cao tốc trước khi tiếp nhiên liệu (`Zero-Leftover Refuel Sprint`).
  - **H4**: Độ trung gian đường bộ dự báo tắc đường (`road_betweenness`).
  - **H5**: Giá ẩn nhiên liệu động theo khoảng cách tới Xe tiếp xăng (`compute_dynamic_fuel_shadow_price`).
  - **H6**: Đấu giá Regret-2 đa tác nhân (`Regret-2 Auction Bonus`).
  - **H7**: Chèn điểm trung gian trên đường đi (`find_best_via_spot`) & Tối ưu cục bộ **2-Opt** (`optimize_spot_sequence_2opt`).
- [hexudon/solver.py](file:///E:/procon/hexudon/solver.py): Bộ giải `HexudonSolver` tích hợp chọn vai trò xe bằng mô phỏng toàn trận (`select_roles`), Portfolio + Rollout + 2-Opt + 1-Day Lookahead (`plan_day`).
- [hexudon/arena.py](file:///E:/procon/hexudon/arena.py): Đấu trường đối kháng 4 đội chạy đồng thời trên cùng bản đồ, chia sẻ lưu lượng giao thông đường bộ (`MultiTeamArena`).
- [hexudon/client.py](file:///E:/procon/hexudon/client.py): `MatchRunner` và `ContestApiClient` kèm chiến thuật **Dual-Commit Submission** (`plan_and_submit_dual_commit`) bảo toàn Ưu tiên 4.
- [visualizer.html](file:///E:/procon/visualizer.html): Giao diện trực quan hóa bản đồ lục giác HTML5 Canvas tương tác.

## 2. Hướng dẫn Chạy Nhanh

### Chạy Bộ Kiểm thử Tự động (8/8 Unit & Tournament Tests)
```powershell
cd E:\procon
python -m unittest tests/test_hexudon.py -v
```

### Chạy Benchmark & Giải Đấu Đối Kháng 4 Đội
```powershell
cd E:\procon
python run_benchmark.py
python build_visualizer.py
```

### Biên dịch lại Lõi C++20 (nếu chỉnh sửa `cpp_accel.cpp`)
```powershell
C:\msys64\ucrt64\bin\g++.exe -O3 -march=native -std=c++20 -shared -static -o E:\procon\hexudon\hexudon_fast.dll E:\procon\hexudon\cpp_accel.cpp
```
