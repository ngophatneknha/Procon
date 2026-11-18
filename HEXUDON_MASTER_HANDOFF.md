# PROCON VIỆT NAM 2026 — TÀI LIỆU TỔNG HỢP & CHUYỂN GIAO HỆ THỐNG HEXUDON (MASTER HANDOFF)

> **Mục đích tài liệu:** Tổng hợp toàn bộ luật thi đấu cốt lõi, kiến trúc mã nguồn tại `E:\procon`, hệ thống thuật toán & 7 Heuristic (H1–H7), các lỗi kỹ thuật đã tự phản biện & khắc phục, kết quả benchmark/đối kháng mới nhất, và mẫu prompt sẵn sàng để tái sử dụng nguyên ngữ cảnh trong các đoạn chat tiếp theo.

---

## 1. Tóm tắt Đề bài & Luật Thi đấu Cốt lõi (Procon Vietnam 2026 — HEXUDON)

Nguồn đặc tả gốc: `E:\procon\2026_Procon_Problem VI.pdf`.

### 1.1. Bản đồ & Hệ tọa độ Lục giác (`even-r` pointy-top)
- **Kích thước bản đồ:** Chiều rộng $W \in [8, 32]$, chiều cao $H \in [8, 32]$ (tối đa $32 \times 32 = 1024$ ô).
- **Định danh ô (`cell_id`):** Số nguyên từ $0$ đến $(H \times W - 1)$, với `cell_id = r * W + c` ($0 \le r < H, 0 \le c < W$).
- **Hình học lưới (`even-r`, Hình 1 trong đề):** Lưới lục giác đỉnh nhọn, các **hàng chẵn** ($r \bmod 2 = 0$) lệch sang **phải** nửa ô so với **hàng lẻ** ($r \bmod 2 = 1$).
  - **6 ô liền kề của hàng chẵn ($r \bmod 2 = 0$):** `(0, -1), (0, 1), (-1, 0), (-1, 1), (1, 0), (1, 1)`
  - **6 ô liền kề của hàng lẻ ($r \bmod 2 = 1$):** `(0, -1), (0, 1), (-1, -1), (-1, 0), (1, -1), (1, 0)`
  - **Chuyển đổi tọa độ trục (`axial` $(q, r)$) để tính khoảng cách lục giác chính xác (`hex_distance`):**
    ```python
    q = c - ((r + (r & 1)) // 2)
    hex_dist = (abs(q1 - q2) + abs(r1 - r2) + abs((q1 - q2) + (r1 - r2))) // 2
    ```
- **Tính liên thông:** Mọi ô không phải Ao đều liên thông với nhau.

### 1.2. Địa hình, Chi phí Di chuyển & Quy tắc "Ô Xuất Phát" (Bảng 1)

| Loại địa hình | Trạng thái | Số bước (Steps) | Nhiên liệu (Fuel - Xe tuần tra) | Ghi chú |
| :--- | :--- | :---: | :---: | :--- |
| **Đồng bằng (`PLAIN`)** | Cố định | **2** | **1** | Nơi đặt vị trí xuất phát & điểm đến (Udon) |
| **Núi (`MOUNTAIN`)** | Cố định | **3** | **2** | Chi phí cao |
| **Ao (`POND`)** | Cố định | — | — | **Không thể đi vào** (đi vào = Invalid) |
| **Đường bộ (`ROAD`)** | Thông thoáng (`SMOOTH`) | **1** | **2** | Nhanh nhất, đốt 2 nhiên liệu |
| **Đường bộ (`ROAD`)** | Đông đúc (`CONGESTED`) | **2** | **2** | Khi lưu lượng $\in [T_{\text{đông}}, T_{\text{tắc}})$ |
| **Đường bộ (`ROAD`)** | Ùn tắc (`JAM`) | **4** | **2** | Khi lưu lượng $\ge T_{\text{tắc}}$ |

> **QUY TẮC QUAN TRỌNG (Departure-Cell Rule):**
> Khi tác nhân nhận lệnh di chuyển (`MOVE`) từ ô hiện tại $u$ sang ô kề $v$ ($v \neq \text{POND}$), **số bước cần thực hiện** và **lượng nhiên liệu tiêu thụ** được tính theo **loại địa hình của ô hiện tại $u$** (tại thời điểm bắt đầu nhận lệnh), KHÔNG phải ô đích $v$. Tác nhân chỉ chuyển sang ô $v$ sau khi hoàn tất đủ số bước của ô $u$.

### 1.3. Lưu lượng Giao thông Đường bộ
- Ngày 1: Tất cả các ô `ROAD` ở trạng thái `SMOOTH` (1 bước).
- Ngày 2: Tính dựa trên lưu lượng giao thông của **Ngày 1** chia cho số lượng đội (`num_teams`).
- Ngày $d \ge 3$: Tính bằng tổng số bước dừng của **tất cả các tác nhân thuộc tất cả các đội** trên ô đường đó trong **2 ngày trước đó** (Ngày $d-1$ và Ngày $d-2$), rồi chia cho `num_teams`.
- Ngưỡng phân loại: `< congested_threshold` $\to$ `SMOOTH`; $\in [\text{congested\_threshold}, \text{jam\_threshold})$ $\to$ `CONGESTED`; $\ge \text{jam\_threshold}$ $\to$ `JAM`. Trạng thái đường cố định trong suốt cả ngày và giống nhau cho mọi đội.

### 1.4. Tác nhân, Kho Udon, Nhiên liệu & Tiếp nhiên liệu
- **Thời gian:** Trận đấu kéo dài $D \in [4, 10]$ ngày; mỗi ngày có `steps_per_day[day-1]` bước (có thể thay đổi theo từng ngày).
- **Số lượng tác nhân:** $N \in [3, 8]$ tác nhân/đội. Nhiều tác nhân (cùng đội hoặc khác đội) có thể đứng chung một ô.
- **Phân loại (chọn 1 lần trước Ngày 1, cố định cả trận):**
  - **Xe tuần tra (`PATROL`):** Thu thập Udon tại các Điểm đến (`Spot`); bình xăng tối đa `max_fuel`; tiêu hao nhiên liệu khi `MOVE`; đứng đợi (`WAIT`) tốn 0 nhiên liệu.
  - **Xe tiếp nhiên liệu (`REFUEL`):** Không thu thập được Udon; **nhiên liệu vô hạn (di chuyển tốn 0 nhiên liệu)**; khi ở cùng ô với Xe tuần tra trong $\ge 1$ bước, nhiên liệu của Xe tuần tra tự động được nạp đầy lên `max_fuel`.
- **Thu thập Udon & Kho dự trữ (`Spot` & `max_stock`):**
  - Mỗi `Spot` nằm trên 1 ô `PLAIN` và thuộc chính xác 1 chuỗi nhượng quyền (`chain_id`).
  - Mỗi Xe tuần tra chỉ thu thập được tối đa **1 phần Udon tại mỗi điểm trong mỗi ngày** (ở lần ghé đầu tiên trong ngày đó).
  - Mức dự trữ tối đa mỗi điểm từ $1 \dots N$, được **nạp đầy lại mức tối đa vào đầu mỗi ngày**, và **độc lập cho từng đội** (đối thủ ăn không làm giảm kho của đội mình).
- **Chuyển giao qua Ngày mới (Lưu ý sống còn):**
  - Vị trí cuối ngày và **lượng nhiên liệu còn lại của Xe tuần tra** được giữ nguyên sang Ngày $d+1$ (**nhiên liệu KHÔNG tự hồi phục qua ngày mới**).

### 1.5. Các Lỗi Dẫn Đến Invalid (Zero-Tolerance)
Toàn bộ câu trả lời trong ngày bị tính là `Invalid` nếu xảy ra bất kỳ lỗi nào sau đây:
1. Di chuyển sang ô không liền kề hoặc đi vào ô `POND`.
2. Xe tuần tra thực hiện `MOVE` khi `fuel < fuel_cost(current_cell)`.
3. Bất kỳ tác nhân nào thực hiện `MOVE` khi `remaining_steps < step_cost(current_cell)`.
4. Không lấp đầy số bước còn lại ở cuối ngày bằng lệnh `WAIT` (hoặc tổng số bước của dãy lệnh không khớp `max_steps`).

### 1.6. Thứ tự Ưu tiên Thắng cuộc (4 Tiêu chí Từ điển Tuyệt đối + Bốc thăm)
1. **Ưu tiên 1 ($F_1$):** Tổng số **loại Udon (`chain_id`) khác nhau** thu thập được trong **toàn trận đấu**.
2. **Ưu tiên 2 ($F_2$):** Tổng lũy kế số **loại Udon khác nhau thu thập được mỗi ngày** ($\sum_{d=1}^{D} |\text{Chains}(d)|$).
3. **Ưu tiên 3 ($F_3$):** Tổng số **phần Udon (`portions`)** thu thập được trong cả trận đấu.
4. **Ưu tiên 4 ($F_4$):** Tổng **thời gian phản hồi lũy kế thấp nhất** cho **câu trả lời hợp lệ cuối cùng** được gửi vào cuối mỗi ngày.
5. **Ưu tiên 5:** Tung xúc xắc hoặc tuyên bố hòa.

---

## 2. Kiến trúc Mã nguồn tại `E:\procon` (Architecture & File Map)

| Đường dẫn tệp | Thành phần chính (`Classes / Functions`) | Vai trò trong hệ thống |
| :--- | :--- | :--- |
| `E:\procon\hexudon\__init__.py` | Public package exports | Xuất các lớp dữ liệu, engine, heuristics, solver và generator |
| `E:\procon\hexudon\models.py` | `TerrainType`, `RoadState`, `AgentRole`, `ActionType`, `Action`, `Spot`, `AgentState`, `MapConfig`, `DayInput`, `StepFrame`, `DayResult`, `MatchScore`, `get_terrain_step_cost`, `get_terrain_fuel_cost` | Định nghĩa cấu trúc dữ liệu chuẩn, chi phí địa hình Bảng 1, tuần tự hóa/giải tuần tự hóa JSON |
| `E:\procon\hexudon\engine.py` | `HexGrid` (`id_to_rc`, `rc_to_id`, `id_to_axial`, `hex_distance`, `is_adjacent`, `is_passable`, `shortest_paths_from`, `reconstruct_path`), `HexudonEngine` (`create_initial_agents`, `compute_road_states`, `simulate_day`) | Hình học lục giác `even-r`, Dijkstra đa tiêu chí bằng Python, bộ mô phỏng step-by-step & Validator nghiêm ngặt 100% theo luật |
| `E:\procon\hexudon\cpp_accel.cpp` | `compute_apsp_cpp` | Lõi C++20 tính All-Pairs Shortest Paths ở 4 chế độ (`0=steps`, `1=fuel`, `2=balanced`, `3=fuel_heavy`) với bộ phá hòa ưu tiên đi qua nhiều `Spot` nhất (`-nsp`) |
| `E:\procon\hexudon\hexudon_fast.dll` | Thư viện nhị phân đã biên dịch (`g++ -O3 -march=native -std=c++20 -shared -static`) | Thực thi APSP native tốc độ cao cho Python gọi qua `ctypes` |
| `E:\procon\hexudon\fast_apsp.py` | `has_cpp_accelerator`, `compute_apsp_fast`, `_GLOBAL_APSP_CACHE` | Wrapper `ctypes` gọi `hexudon_fast.dll`, cắt slice trực tiếp từ buffer và lưu cache kết quả APSP |
| `E:\procon\hexudon\heuristics.py` | `HexudonHeuristics` (`chain_scarcity`, `spot_isolation`, `road_betweenness`, `compute_gravity_potential`, `compute_dynamic_fuel_shadow_price`, `find_best_via_spot`), `optimize_spot_sequence_2opt` | Tính toán các Heuristic đặc thù H1–H7 và bộ tối ưu cục bộ 2-Opt |
| `E:\procon\hexudon\solver.py` | `_AgentPlanBuilder`, `HexudonSolver` (`select_roles`, `_quick_rollout_roles`, `plan_day`, `_run_tour_local_search`, `_build_schedule`, `_step_off_road_if_needed`, `_record_spot_collection`, `_try_schedule_rendezvous`) | Bộ giải chính: chọn vai trò bằng mô phỏng toàn trận, lập lịch đa tác nhân, Local Search tổ hợp và Lookahead Day $d+1$ |
| `E:\procon\hexudon\arena.py` | `BotCompetitor`, `MultiTeamArena` (`create_standard_competitors`, `run_tournament`) | Đấu trường mô phỏng 4 đội chạy đồng thời trên cùng bản đồ, chia sẻ lưu lượng giao thông đường bộ |
| `E:\procon\hexudon\generator.py` | `generate_map_config`, `_is_connected` | Bộ sinh bản đồ ngẫu nhiên $8 \dots 32$ ô, đảm bảo liên thông và đúng ràng buộc điểm đến / điểm xuất phát |
| `E:\procon\hexudon\client.py` | `MatchRunner` (`run_match`), `ContestApiClient` (`get_map_config`, `submit_roles`, `submit_day_actions`, `plan_and_submit_dual_commit`) | Bộ chạy trận đấu nội bộ (xuất replay) và HTTP/JSON API client kèm chiến thuật gửi kép Dual-Commit |
| `E:\procon\run_benchmark.py` | `run_all_benchmarks` | Chạy benchmark đơn đội và giải đấu đối kháng 4 đội trên 4 kịch bản ($10\times 10 \to 32\times 32$), xuất `E:\procon\sample_replays.json` |
| `E:\procon\build_visualizer.py` | `build_visualizer` | Đóng gói `sample_replays.json` thành giao diện trực quan hóa độc lập `E:\procon\visualizer.html` |
| `E:\procon\visualizer.html` | HTML5 Canvas Interactive Replay UI | Trực quan hóa bản đồ `even-r`, trạng thái tắc đường, vị trí/xăng của từng xe, tiến trình từng step & bảng điểm 4 tiêu chí |
| `E:\procon\tests\test_hexudon.py` | `TestHexudonRules` (8 bài test) | Kiểm thử hình học lưới, quy tắc ô xuất phát, tiếp xăng, từ chối lệnh invalid, khớp C++ vs Python Dijkstra, Heuristic/2-Opt, Arena và End-to-End |
| `E:\procon\README.md` | Tài liệu hướng dẫn chạy nhanh | Tóm tắt cấu trúc thư mục và các lệnh CLI |

---

## 3. Chi tiết Thuật toán, 7 Heuristic (H1–H7) & Local Search Tổ hợp

### 3.1. Chọn Vai Trò Đầu Trận Bằng Mô Phỏng Toàn Trận (`select_roles`)
- Dựa trên phân tích khoảng cách trung bình từ vị trí xuất phát tới tất cả các quán Udon (`centrality`), sinh ra tập các phương án phân vai ứng viên: 0 xe tiếp xăng (nếu bình xăng đủ lớn), 1 xe tiếp xăng ở vị trí trung tâm nhất/nhì, hoặc 2 xe tiếp xăng tách biệt hai nửa bản đồ.
- Khi `use_simulation_rollout=True`, chạy thử toàn bộ $D$ ngày trên `MapConfig` cho từng ứng viên và chọn đội hình có bộ điểm $(F_1, F_2, F_3)$ cao nhất.

### 3.2. C++20 Spot-Aware APSP (`compute_apsp_cpp`)
- Hỗ trợ 4 chế độ chi phí: `steps` (tối thiểu bước), `fuel` (tối thiểu xăng), `balanced` (`steps * 2 + fuel`), `fuel_heavy` (`steps + fuel * 3`).
- **Spot-Collecting Tie-Breaker (`-nsp`):** Trong hàng đợi ưu tiên Dijkstra, tiêu chí phụ cuối cùng là **tối đa hóa số ô `Spot` đi ngang qua (`is_spot`)**. Khi có nhiều đường đi ngắn nhất bằng nhau về `(steps, fuel)`, đường đi tự động uốn qua các quán Udon nằm dọc đường để thu thập phần thưởng miễn phí.

### 3.3. Bảy Heuristic Đặc Thù (H1–H7)
1. **H1 — Chain Scarcity & Boundary Isolation (`chain_scarcity`, `spot_isolation`):**
   - $\text{Scarcity}(c) = (1 / \text{count}(c))^{0.65}$ kết hợp độ cô lập ở rìa bản đồ, giúp tăng trọng số ưu tiên cho các chuỗi hiếm (chỉ có 1 quán) hoặc các quán ở góc xa khi có xe đi gần tới đó.
2. **H2 — Hex Gravity Potential Field (`compute_gravity_potential`):**
   - Tính thế năng cụm quán xung quanh mỗi `Spot` trong bán kính $\le 10$ bước, ưu tiên kéo xe vào các vùng có mật độ cao chuỗi chưa ghé thăm trong ngày/toàn trận.
3. **H3 — Zero-Leftover Refuel Sprint & Highway Tanker Routing (`apsp_refuel`):**
   - Xe tiếp nhiên liệu (`REFUEL`) tốn 0 xăng nên **luôn di chuyển theo `apsp_refuel` (đường bộ thông thoáng 1 bước/ô)** để bám theo tiếp tế siêu tốc.
4. **H4 — Road Betweenness Centrality & Anti-Self-Jamming (`road_betweenness`, `_step_off_road_if_needed`):**
   - Tính mức độ huyết mạch của các ô đường bộ qua mật độ đường đi ngắn nhất giữa các quán Udon; cuối ngày khi hết việc, cả Xe tuần tra lẫn Xe tiếp xăng chủ động bước ra khỏi ô `ROAD` sang ô `PLAIN` (ưu tiên `Spot`) trước khi `WAIT`, tránh tự làm tắc đường sang ngày hôm sau.
5. **H5 — Dynamic Fuel Shadow Price (`compute_dynamic_fuel_shadow_price`):**
   - Định giá quy đổi động giữa 1 đơn vị xăng và 1 bước đi dựa trên tỷ lệ xăng còn lại (`max_fuel / fuel`) và khoảng cách tới Xe tiếp xăng gần nhất.
6. **H6 — Regret-2 Multi-Agent Auction Bonus:**
   - Trong `_build_schedule`, nếu một xe tuần tra gần một chuỗi mới hơn hẳn xe tuần tra gần thứ hai (`other_min_steps > my_arrival + 2`), tăng trọng số ưu tiên (`regret_gap`) để xe đó giữ chắc quyền thu thập chuỗi đó.
7. **H7 — Via-Spot Detour Augmentation (`find_best_via_spot`) & Causal Forward 2-Opt:**
   - Trước khi đi thẳng `u -> target_v`, kiểm tra xem có điểm `w` trung gian nào chỉ làm phát sinh `0` bước phụ (hoặc $\le 2$ bước nếu `w` mở khóa chuỗi mới trong ngày) để ghé qua thu thập luôn; đồng thời kiểm tra đảo thứ tự cặp điểm $(s_1, s_2) \leftrightarrow (s_2, s_1)$.

### 3.4. Pipeline 4 Pha Hàng Ngày (`plan_day`) & Chiến thuật Gửi Kép (`Dual-Commit`)
1. **Phase 1 & 2 (Portfolio + Guided Stochastic Rollouts):** Chạy tập cấu hình xác định và các rollout ngẫu nhiên trong 50% ngân sách thời gian.
2. **Phase 3 — Combinatorial Tour Local Search (`_run_tour_local_search`):** Trích xuất chuỗi điểm đến thực tế $\mathcal{T} = \{pid: [s_1, s_2, \dots]\}$ của các Xe tuần tra và chạy 3 toán tử:
   - **Op 1 (`Intra-Agent 2-Opt`):** Rút gọn lộ trình của từng xe bằng `optimize_spot_sequence_2opt`, giải phóng bước thừa để ăn thêm điểm mới.
   - **Op 2 (`Missing-Chain Targeted Injection`):** Kiểm tra các chuỗi bị bỏ sót trong ngày (`all_chains - chains_collected_today`), tính độ lệch bước nhỏ nhất (`detour`) và cưỡng bức chèn vào đầu/giữa lộ trình của xe phù hợp nhất rồi chạy lại 2-Opt.
   - **Op 3 (`Inter-Agent Spot Swap`):** Hoán đổi điểm đến giữa các cặp Xe tuần tra để triệt tiêu các lộ trình cắt chéo nhau.
3. **Phase 4 — True 1-Day Lookahead Rollout (`Day d -> Day d+1`):** Với tối đa 4 phương án đỉnh khác nhau về vị trí/nhiên liệu cuối ngày, mô phỏng thử tiếp sang Ngày $d+1$ để chọn phương án tối ưu hóa tổng điểm 2 ngày liên tiếp (tránh trường hợp ăn tham 1 phần cuối ngày khiến đầu ngày sau cạn xăng).
4. **Dual-Commit Submission (`ContestApiClient.plan_and_submit_dual_commit`):**
   - Gửi ngay lần 1 (`time_budget_ms=15.0`) để khóa mốc thời gian phản hồi cực thấp cho **Ưu tiên 4**.
   - Tiếp tục tìm kiếm sâu (`deep_budget_ms=500.0`) và **CHỈ gửi lại (resubmit)** nếu tìm được phương án có bộ điểm $(F_1, F_2, F_3)$ **lớn hơn hẳn** (tuyệt đối không gửi lại khi hòa điểm).

---

## 4. Các Lỗi Kỹ Thuật Đã Tự Phản Biện & Khắc Phục (Audit Lessons Learned)

Khi thực hiện rà soát kỹ thuật (Technical Audit), chúng ta đã phát hiện và sửa triệt để 6 lỗi/điểm yếu sau — **cần đặc biệt lưu ý không lặp lại khi mở rộng hoặc chuyển sang C++ thuần**:

1. **Quên ghi nhận thu thập Udon tại ô xuất phát đầu Ngày $d \ge 2$ (`Audit Issue 1`):**
   - *Nguyên nhân:* Cuối Ngày $d-1$, Xe tuần tra thường dừng trên một ô `Spot`. Sang Step 1 của Ngày $d$, kho tại ô đó đã hồi đầy; khi xe bắt đầu `MOVE` ra khỏi ô `PLAIN` đó (mất 2 bước), cuối Step 1 xe vẫn đang ở ô xuất phát nên `engine.py` tự động thu thập Udon tại đó. Code cũ quên ghi nhận sự kiện này nên điều xe quay ngược lại ô xuất phát.
   - *Đã sửa:* Trong `_build_schedule`, khi `use_2opt` được bật và `pb.step == 0` trên ô `Spot`, tự động ghi nhận thu thập ô xuất phát trước khi di chuyển.
2. **Lệch pha thời gian của Xe tiếp nhiên liệu cuối ngày (`Audit Issue 2`):**
   - *Nguyên nhân:* Vòng lặp điều phối Xe tiếp xăng cuối ngày chỉ đọc `pb.cell` (vị trí cuối ngày của Xe tuần tra) mà không so khớp với `pb.step` (thời điểm thực tế xe tuần tra mới tới đó), dẫn đến việc Xe tiếp xăng chạy tới sớm, đứng chờ 1 bước lúc xe tuần tra chưa tới, rồi tự gán ảo đã đổ xăng.
   - *Đã sửa:* Đồng bộ chính xác mốc hẹn `t_meet = max(rb.step + d_s, pb.step)`, yêu cầu `t_meet + 1 <= max_steps` và cho `rb` đợi tới đúng `target_pb.step` cộng thêm 1 bước chung ô (`add_wait(1)`).
3. **Tràn số nguyên 32-bit trong C++ APSP ở chế độ `balanced` (`cpp_accel.cpp`):**
   - *Nguyên nhân:* Giá trị chưa chạm tới là `INF = 1_000_000_000`. Khi tính `d_s[v] * 2 + d_f[v]` trong `int32_t`, biểu thức `3 * 10^9` bị tràn số có dấu (`signed overflow`) thành số âm, làm `balanced` APSP sai.
   - *Đã sửa:* Ép kiểu `static_cast<int64_t>` khi tính `old_p` cho cả chế độ `balanced` và `fuel_heavy`.
4. **Thay thế "Simulated Annealing giả" bằng Local Search tổ hợp thực thụ (`Audit Issue 4`):**
   - *Nguyên nhân:* Việc chỉ nhiễu ngẫu nhiên trọng số heuristic không giải quyết được các nút thắt thứ tự điểm đến.
   - *Đã sửa:* Bổ sung `_run_tour_local_search` thao tác trực tiếp trên chuỗi `Spot` của các xe (2-Opt, Missing-Chain Injection, Inter-Agent Swap).
5. **Tối ưu hiệu năng `ctypes` & thu gọn tập điểm hẹn trên bản đồ $32 \times 32$:**
   - Cắt lát trực tiếp trên mảng `ctypes` kết hợp `_GLOBAL_APSP_CACHE` trong `fast_apsp.py` (tránh copy 3 triệu phần tử mỗi lần gọi).
   - Khi `num_cells > 256`, trong `_try_schedule_rendezvous` thu gọn tập điểm hẹn `candidate_cells` về `{pb.cell, rb.cell} ∪ passable_neighbors[pb.cell] ∪ spots ∪ shortest_path(rb -> pb)`, giúp tăng tốc hơn 2x trên bản đồ $32 \times 32$.
6. **Xây dựng đối thủ độc lập & Kịch bản Stress-Test $32 \times 32$ (`Audit Issue 5`):**
   - Thay thế các bot đối thủ sơ khai bằng `Voronoi Territory Partition + TSP 2-Opt Bot` và `Multi-Agent Chain-Auction + Gravity Field Bot` trong `arena.py`, đồng thời bổ sung kịch bản cực đại $32 \times 32$ (1024 ô, 45 quán, 24 chuỗi, 8 ngày).
   - *Điểm còn mở để nâng cấp thêm nếu muốn:* Trong `_build_schedule`, các xe vẫn chọn đích lần lượt theo thời điểm kết thúc chặng trước (chưa hoàn toàn bước từng step song song khi các xe tranh nhau cùng 1 ô có `max_stock = 1`), và khi có đặc tả API chính thức từ BTC cần cập nhật lại đường dẫn endpoint/schema JSON trong `ContestApiClient` (`client.py`).

---

## 5. Kết quả Kiểm thử & Benchmark Thực tế (Baseline Metrics)

Toàn bộ kết quả dưới đây được ghi nhận trực tiếp sau lần chỉnh sửa cuối cùng (8/8 unit tests trong `tests/test_hexudon.py` pass trong `0.798s`; `run_benchmark.py` thoát mã `0`):

### 5.1. Phần 1 — Hiệu năng Tối ưu Đơn đội (`MatchRunner`)

| Kịch bản (`generator.py`) | Đội hình vai trò chọn được | Ưu tiên 1 ($F_1$) | Ưu tiên 2 ($F_2$) | Ưu tiên 3 ($F_3$: Portions) | Ưu tiên 4 ($F_4$: Response Time) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Scenario 1:** 10x10 (100 ô), 14 Spot, 8 Chuỗi, 5 Ngày, Fuel=14, Seed=101 | 3 PATROL + 1 REFUEL | **8 / 8 (100.0%)** | **40** *(100% Max)* | **101** | **223.66 ms** *(44.73 ms/ngày)* |
| **Scenario 2:** 16x14 (224 ô), 24 Spot, 14 Chuỗi, 6 Ngày, Fuel=18, Seed=2026 | 4 PATROL + 2 REFUEL | **14 / 14 (100.0%)** | **84** *(100% Max)* | **169** | **687.97 ms** *(114.66 ms/ngày)* |
| **Scenario 3:** 22x18 (396 ô), 32 Spot, 18 Chuỗi, 7 Ngày, Fuel=16, Seed=777 | 6 PATROL + 2 REFUEL | **18 / 18 (100.0%)** | **124** *(Max 126)* | **227** | **732.46 ms** *(104.64 ms/ngày)* |
| **Scenario 4 (Extreme):** 32x32 (1024 ô), 45 Spot, 24 Chuỗi, 8 Ngày, Fuel=18, Seed=9999 | 6 PATROL + 2 REFUEL | **24 / 24 (100.0%)** | **143** *(Max 192)* | **171** | **3550.67 ms** *(443.83 ms/ngày)* |

### 5.2. Phần 2 — Giải đấu Đối kháng 4 Đội Đồng thời (`MultiTeamArena`, chia sẻ lưu lượng đường bộ)

| Kịch bản | Hạng 1 (`Grandmaster Solver - Ours`) | Hạng 2 | Hạng 3 | Hạng 4 |
| :--- | :--- | :--- | :--- | :--- |
| **Scenario 1 (10x10, 8 chuỗi)** | **🏆 P1=8/8, P2=40, P3=101** *(249.1ms)* | Greedy: P1=8/8, P2=40, P3=82 | Auction: P1=8/8, P2=40, P3=71 | Voronoi: P1=8/8, P2=39, P3=73 |
| **Scenario 2 (16x14, 14 chuỗi)** | **🏆 P1=14/14, P2=83, P3=162** *(763.0ms)* | Greedy: P1=14/14, P2=79, P3=138 | Voronoi: P1=14/14, P2=77, P3=147 | Auction: P1=14/14, P2=76, P3=138 |
| **Scenario 3 (22x18, 18 chuỗi)** | **🏆 P1=18/18, P2=124, P3=221** *(954.2ms)* | Greedy: P1=18/18, P2=117, P3=207 | Auction: P1=18/18, P2=117, P3=197 | Voronoi: P1=18/18, P2=107, P3=186 |
| **Scenario 4 (32x32, 24 chuỗi)** | **🏆 P1=24/24, P2=143, P3=171** *(3832.8ms)* | Auction: P1=24/24, P2=118, P3=163 | Greedy: P1=24/24, P2=112, P3=130 | Voronoi: P1=23/24, P2=93, P3=130 |

---

## 6. Lệnh Chạy Nhanh & Mẫu Prompt Tái Sử Dụng Cho Đoạn Chat Mới

### 6.1. Các lệnh PowerShell thiết yếu tại `E:\procon`
```powershell
# 1. Chạy toàn bộ 8 bài kiểm thử (luật, C++ DLL vs Python, heuristic, đấu trường 4 đội)
cd E:\procon
python -m unittest tests/test_hexudon.py -v

# 2. Chạy benchmark đơn đội + giải đấu 4 đội & xuất sample_replays.json
cd E:\procon
python run_benchmark.py

# 3. Sinh lại giao diện trực quan hóa HTML5 Canvas (mở E:\procon\visualizer.html trên trình duyệt)
cd E:\procon
python build_visualizer.py

# 4. Biên dịch lại lõi C++20 nếu chỉnh sửa hexudon/cpp_accel.cpp
C:\msys64\ucrt64\bin\g++.exe -O3 -march=native -std=c++20 -shared -static -o E:\procon\hexudon\hexudon_fast.dll E:\procon\hexudon\cpp_accel.cpp
```

### 6.2. Mẫu Prompt Copy-Paste Khi Mở Đoạn Chat Mới
Bạn chỉ cần dán đoạn prompt sau vào đầu bất kỳ cuộc trò chuyện mới nào (hoặc đính kèm trực tiếp tệp `E:\procon\HEXUDON_MASTER_HANDOFF.md`):

```text
Tôi đang phát triển bot thi đấu giải Nhất Procon Việt Nam 2026 — bài toán Tối ưu hoá lộ trình HEXUDON tại thư mục E:\procon.
Hãy đọc toàn bộ tệp E:\procon\HEXUDON_MASTER_HANDOFF.md để nắm đầy đủ:
1. Đề bài gốc (E:\procon\2026_Procon_Problem VI.pdf) và toàn bộ luật di chuyển, nhiên liệu, giao thông, 4 tiêu chí thắng cuộc.
2. Kiến trúc mã nguồn hiện tại (Python + C++20 DLL hexudon_fast.dll + 7 Heuristic H1-H7 + Local Search + MultiTeamArena + Visualizer).
3. Các lỗi kỹ thuật đã audit và baseline benchmark hiện tại.

Sau khi đọc xong, hãy hỗ trợ tôi nhiệm vụ tiếp theo: [ĐIỀN YÊU CẦU MỚI CỦA BẠN: ví dụ "Khớp nối schema API JSON chính thức của BTC vào client.py" / "Viết lại solver lõi bằng C++ thuần" / "Tối ưu điểm P2 và P3 trên map 32x32"].
```
